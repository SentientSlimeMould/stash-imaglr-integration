# SPDX-License-Identifier: AGPL-3.0-only
import os
import shutil
import struct
import tempfile
import unittest

from imaglr_integration.media import metadata_strip as ms

from . import media_fixtures as mf


class JpegStripTest(unittest.TestCase):
    def test_removes_exif_xmp_iptc_comment_and_trailer(self):
        dirty = mf.add_jpeg_metadata(mf.JPEG_16x8, orientation=6)
        self.assertTrue(mf.secrets_in(dirty))
        clean = ms.strip_bytes(dirty)
        self.assertEqual(mf.secrets_in(clean), [])
        self.assertNotIn(b"Photoshop 3.0", clean)
        self.assertNotIn(b"Lavc", clean)  # ffmpeg's own encoder comment
        self.assertTrue(clean.endswith(b"\xff\xd9"))

    def test_keeps_jfif_icc_adobe_and_image_data(self):
        clean = ms.strip_bytes(mf.add_jpeg_metadata(mf.JPEG_16x8))
        self.assertTrue(clean.startswith(b"\xff\xd8\xff\xe0\x00\x10JFIF\0"))
        self.assertIn(mf.ICC_SEGMENT, clean)
        self.assertIn(mf.ADOBE_SEGMENT, clean)
        # Everything from the first quantisation table to EOI is untouched.
        start = mf.JPEG_16x8.index(b"\xff\xdb")
        self.assertTrue(clean.endswith(mf.JPEG_16x8[start:]))

    def test_idempotent_and_handles_fill_bytes_and_stuffing(self):
        once = ms.strip_bytes(mf.add_jpeg_metadata(mf.JPEG_16x8))
        self.assertEqual(ms.strip_bytes(once), once)
        # Fill bytes between header segments are dropped (still valid); FF00 stuffing and RSTn inside the
        # scan survive intact.
        sos = once.index(b"\xff\xda")
        self.assertEqual(ms.strip_bytes(once[:sos] + b"\xff\xff" + once[sos:]), once)
        scan = b"\xff\xd8" + mf._segment(0xDA, b"\x01\x01\0\0\x3f\0") + b"\x12\xff\x00\x34\xff\xd0\x56\xff\xd9"
        self.assertEqual(ms.strip_bytes(scan), scan)

    def test_rejects_non_jpeg_and_truncation(self):
        with self.assertRaises(ms.StripError):
            ms.strip_bytes(b"not an image at all")
        with self.assertRaises(ms.StripError):
            ms.strip_bytes(mf.add_jpeg_metadata(mf.JPEG_16x8)[:40])


class PngStripTest(unittest.TestCase):
    def chunk_types(self, data):
        pos, kinds = 8, []
        while pos < len(data):
            length, kind = struct.unpack_from(">I4s", data, pos)
            kinds.append(kind)
            pos += 12 + length
        return kinds

    def test_drops_text_exif_time_keeps_colour_and_image_chunks(self):
        dirty = mf.add_png_metadata(mf.make_png(8, 4, alpha=True), orientation=6)
        clean = ms.strip_bytes(dirty)
        self.assertEqual(mf.secrets_in(clean), [])
        self.assertEqual(self.chunk_types(clean), [b"IHDR", b"iCCP", b"pHYs", b"IDAT", b"IEND"])

    def test_apng_chunks_survive(self):
        png = mf.make_png(4, 4)
        actl = mf.png_chunk(b"acTL", b"\0\0\0\x02\0\0\0\0")
        fctl = mf.png_chunk(b"fcTL", b"\0" * 26)
        apng = png[:33] + actl + fctl + png[33:]
        self.assertEqual(ms.strip_bytes(apng), apng)


class WebpStripTest(unittest.TestCase):
    def test_drops_exif_xmp_clears_flags_fixes_size(self):
        for source in (mf.WEBP_LOSSY_16x8, mf.WEBP_LOSSLESS_ALPHA_16x8, mf.WEBP_ANIMATED_16x8):
            dirty = mf.add_webp_metadata(source, orientation=6)
            clean = ms.strip_bytes(dirty)
            self.assertEqual(mf.secrets_in(clean), [])
            self.assertEqual(struct.unpack_from("<I", clean, 4)[0], len(clean) - 8)
            chunks = mf.webp_chunks(clean)
            self.assertEqual(chunks[0][0], b"VP8X")
            self.assertEqual(chunks[0][1][0] & 0x0C, 0)
            self.assertNotIn(b"EXIF", [c[0] for c in chunks])
            self.assertNotIn(b"XMP ", [c[0] for c in chunks])

    def test_animation_and_alpha_flags_are_kept(self):
        clean = ms.strip_bytes(mf.add_webp_metadata(mf.WEBP_ANIMATED_16x8))
        original = mf.webp_chunks(mf.WEBP_ANIMATED_16x8)
        self.assertEqual(clean[20] & 0x12, original[0][1][0] & 0x12)
        self.assertEqual([c for c in mf.webp_chunks(clean) if c[0] == b"ANMF"], [c for c in original if c[0] == b"ANMF"])

    def test_clean_file_is_unchanged(self):
        self.assertEqual(ms.strip_bytes(mf.WEBP_ANIMATED_16x8), mf.WEBP_ANIMATED_16x8)
        self.assertEqual(ms.strip_bytes(mf.WEBP_LOSSY_16x8), mf.WEBP_LOSSY_16x8)


class GifStripTest(unittest.TestCase):
    def test_drops_comments_and_xmp_keeps_loop_and_frames(self):
        dirty = mf.add_gif_metadata(mf.GIF_ANIMATED_16x8)
        self.assertTrue(mf.secrets_in(dirty))
        clean = ms.strip_bytes(dirty)
        self.assertEqual(mf.secrets_in(clean), [])
        self.assertNotIn(b"XMP DataXMP", clean)
        self.assertIn(b"NETSCAPE2.0", clean)
        self.assertEqual(clean, mf.GIF_ANIMATED_16x8)

    def test_other_application_extensions_go(self):
        gif = mf.GIF_ANIMATED_16x8
        pos = 13 + (3 << ((gif[10] & 7) + 1))
        icc = b"\x21\xff\x0bICCRGBG1012" + b"\x04abcd\x00"
        self.assertEqual(ms.strip_bytes(gif[:pos] + icc + gif[pos:]), gif)


class StripFileTest(unittest.TestCase):
    def test_in_place_and_no_leftovers(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "a.jpg")
            with open(path, "wb") as f:
                f.write(mf.add_jpeg_metadata(mf.JPEG_16x8))
            ms.strip_file(path, path)
            with open(path, "rb") as f:
                self.assertEqual(mf.secrets_in(f.read()), [])
            self.assertEqual(os.listdir(tmp), ["a.jpg"])
            bad = os.path.join(tmp, "bad.png")
            with open(bad, "wb") as f:
                f.write(mf.make_png(4, 4)[:-12])  # no IEND
            with self.assertRaises(ms.StripError):
                ms.strip_file(bad, os.path.join(tmp, "out.png"))
            self.assertEqual(sorted(os.listdir(tmp)), ["a.jpg", "bad.png"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

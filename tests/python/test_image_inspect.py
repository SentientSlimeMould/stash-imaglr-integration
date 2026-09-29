# SPDX-License-Identifier: AGPL-3.0-only
import os
import shutil
import tempfile
import unittest

from imaglr_integration.media.image_inspect import ImageFormatError, exif_orientation, inspect_image, sniff_format

from . import media_fixtures as mf


class InspectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def inspect(self, data, name="x"):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(data)
        return inspect_image(path)

    def test_sniff(self):
        self.assertEqual(sniff_format(mf.JPEG_16x8[:16]), "JPEG")
        self.assertEqual(sniff_format(mf.make_png(2, 2)[:16]), "PNG")
        self.assertEqual(sniff_format(mf.WEBP_LOSSY_16x8[:16]), "WEBP")
        self.assertEqual(sniff_format(mf.GIF_ANIMATED_16x8[:16]), "GIF")
        self.assertIsNone(sniff_format(b"II*\0" + b"\0" * 12))  # TIFF

    def test_exif_orientation_both_byte_orders(self):
        self.assertEqual(exif_orientation(mf.exif_tiff(6)), 6)
        self.assertEqual(exif_orientation(b"Exif\0\0" + mf.exif_tiff(8)), 8)
        self.assertEqual(exif_orientation(mf.exif_tiff_big_endian(3)), 3)
        self.assertEqual(exif_orientation(b"garbage"), 1)
        self.assertEqual(exif_orientation(mf.exif_tiff(6)[:20]), 1)  # truncated

    def test_jpeg_reads_orientation(self):
        i = self.inspect(mf.add_jpeg_metadata(mf.JPEG_16x8, orientation=6))
        self.assertEqual((i.format, i.width, i.height, i.orientation), ("JPEG", 16, 8, 6))
        self.assertEqual(i.display_size, (8, 16))
        self.assertFalse(i.has_alpha or i.is_animated)
        self.assertEqual(self.inspect(mf.JPEG_16x8).orientation, 1)

    def test_png_alpha_orientation_and_apng(self):
        self.assertFalse(self.inspect(mf.make_png(10, 6)).has_alpha)
        self.assertTrue(self.inspect(mf.make_png(10, 6, alpha=True)).has_alpha)
        self.assertTrue(self.inspect(mf.make_png(10, 6, trns=True)).has_alpha)
        i = self.inspect(mf.add_png_metadata(mf.make_png(10, 6), orientation=8))
        self.assertEqual((i.format, i.width, i.height, i.orientation), ("PNG", 10, 6, 8))
        png = mf.make_png(4, 4)
        apng = png[:33] + mf.png_chunk(b"acTL", b"\0\0\0\x02\0\0\0\0") + png[33:]
        self.assertTrue(self.inspect(apng).is_animated)

    def test_webp_variants(self):
        lossy = self.inspect(mf.WEBP_LOSSY_16x8)
        self.assertEqual((lossy.format, lossy.width, lossy.height, lossy.has_alpha), ("WEBP", 16, 8, False))
        lossless = self.inspect(mf.WEBP_LOSSLESS_ALPHA_16x8)
        self.assertEqual((lossless.width, lossless.height, lossless.has_alpha), (16, 8, True))
        anim = self.inspect(mf.WEBP_ANIMATED_16x8)
        self.assertEqual((anim.width, anim.height, anim.is_animated), (16, 8, True))
        tagged = self.inspect(mf.add_webp_metadata(mf.WEBP_LOSSY_16x8, orientation=6))
        self.assertEqual((tagged.width, tagged.height, tagged.orientation), (16, 8, 6))

    def test_gif(self):
        i = self.inspect(mf.GIF_ANIMATED_16x8)
        self.assertEqual((i.format, i.width, i.height, i.is_animated, i.orientation), ("GIF", 16, 8, True, 1))
        self.assertTrue(self.inspect(mf.add_gif_metadata(mf.GIF_ANIMATED_16x8)).is_animated)

    def test_unknown_format_needs_ffprobe(self):
        with self.assertRaises(ImageFormatError):
            self.inspect(b"BM" + b"\0" * 60)

    def test_truncated_file_is_an_error(self):
        with self.assertRaises(ImageFormatError):
            self.inspect(mf.JPEG_16x8[:30])


if __name__ == "__main__":
    unittest.main()

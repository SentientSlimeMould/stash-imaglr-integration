# SPDX-License-Identifier: AGPL-3.0-only
"""The lossless strip path of process_image, which needs no ffmpeg. Re-encodes are in test_media_real."""

import os
import shutil
import tempfile
import unittest

from imaglr_integration.media.image_inspect import inspect_image
from imaglr_integration.media.image_plan import ImagePlan, plan_image
from imaglr_integration.media.image_process import ImageTooLarge, _fit, process_image
from imaglr_integration.media.metadata_strip import StripError

from . import media_fixtures as mf

LIMIT = int(40 * 1024 * 1024 * 0.95)
NO_FFMPEG = "/nonexistent/ffmpeg"  # proves the strip path never runs ffmpeg


class StripPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def process(self, src, crop="original", limit=LIMIT):
        info = inspect_image(src)
        plan = plan_image(info, crop, limit)
        return plan, process_image(src, self.out, "photo", plan, info, crop, 0.5, limit, ffmpeg=NO_FFMPEG)

    def test_each_format_is_stripped_losslessly(self):
        cases = [
            ("a.jpg", mf.add_jpeg_metadata(mf.JPEG_16x8), "image/jpeg", "photo.jpg", (16, 8)),
            ("a.png", mf.add_png_metadata(mf.make_png(12, 6, alpha=True)), "image/png", "photo.png", (12, 6)),
            ("a.webp", mf.add_webp_metadata(mf.WEBP_ANIMATED_16x8), "image/webp", "photo.webp", (16, 8)),
            ("a.gif", mf.add_gif_metadata(mf.GIF_ANIMATED_16x8), "image/gif", "photo.gif", (16, 8)),
        ]
        for name, data, mime, out_name, size in cases:
            with self.subTest(name):
                plan, res = self.process(self.write(name, data))
                self.assertEqual(plan.action, "strip")
                self.assertEqual((res.mime, os.path.basename(res.path), (res.width, res.height)), (mime, out_name, size))
                with open(res.path, "rb") as f:
                    out = f.read()
                self.assertEqual(mf.secrets_in(out), [])
                self.assertEqual(res.bytes, len(out))
        self.assertEqual(sorted(os.listdir(self.out)), ["photo.gif", "photo.jpg", "photo.png", "photo.webp"])

    def test_animated_over_limit_after_strip_is_an_error(self):
        src = self.write("a.gif", mf.GIF_ANIMATED_16x8)
        info = inspect_image(src)
        with self.assertRaises(ImageTooLarge):
            process_image(src, self.out, "a", ImagePlan("strip", "GIF"), info, "original", 0.5, 100, ffmpeg=NO_FFMPEG)
        self.assertEqual(os.listdir(self.out), [])

    def test_broken_animation_is_not_reencoded(self):
        src = self.write("a.gif", mf.GIF_ANIMATED_16x8[:-40] + b"\x99")
        info = inspect_image(src)
        with self.assertRaises(StripError):
            process_image(src, self.out, "a", ImagePlan("strip", "GIF"), info, "original", 0.5, LIMIT, ffmpeg=NO_FFMPEG)

    def test_to_video_is_not_handled_here(self):
        src = self.write("a.gif", mf.GIF_ANIMATED_16x8)
        with self.assertRaises(ValueError):
            process_image(src, self.out, "a", ImagePlan("to_video", "MP4"), inspect_image(src), "1:1", 0.5, LIMIT,
                          ffmpeg=NO_FFMPEG)

    def test_fit(self):
        self.assertEqual(_fit(7000, 5000, 6000), (6000, 4285))
        self.assertEqual(_fit(1200, 1600, 1000), (750, 1000))


if __name__ == "__main__":
    unittest.main()

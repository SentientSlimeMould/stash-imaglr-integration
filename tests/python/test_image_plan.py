# SPDX-License-Identifier: AGPL-3.0-only
import unittest

from imaglr_integration.media.image_inspect import ImageInfo
from imaglr_integration.media.image_plan import plan_image, step_down

LIMIT = int(40 * 1024 * 1024 * 0.95)


def info(**kw):
    base = dict(
        format="JPEG", width=4000, height=3000, bytes=2_000_000, orientation=1, has_alpha=False, is_animated=False
    )
    base.update(kw)
    return ImageInfo(**base)


class PlanTest(unittest.TestCase):
    def test_lossless_strip_for_clean_jpeg(self):
        p = plan_image(info(), None, LIMIT)
        self.assertEqual((p.action, p.out_format, p.mime, p.ext), ("strip", "JPEG", "image/jpeg", "jpg"))

    def test_orientation_forces_reencode(self):
        p = plan_image(info(orientation=6), None, LIMIT)
        self.assertEqual(p.action, "reencode")
        self.assertIn("rotate", p.steps[0])
        self.assertEqual(info(orientation=6).display_size, (3000, 4000))

    def test_crop_forces_reencode_and_original_is_not_a_crop(self):
        self.assertEqual(plan_image(info(), "original", LIMIT).action, "strip")
        p = plan_image(info(), "4:5", LIMIT)
        self.assertEqual(p.action, "reencode")
        self.assertTrue(any("crop 4:5" in s for s in p.steps))

    def test_png_keeps_alpha_webp_stays_webp(self):
        self.assertEqual(plan_image(info(format="PNG", has_alpha=True, orientation=6), None, LIMIT).out_format, "PNG")
        self.assertEqual(plan_image(info(format="WEBP"), "1:1", LIMIT).out_format, "WEBP")

    def test_still_gif_reencodes_to_jpeg_or_png(self):
        self.assertEqual(plan_image(info(format="GIF"), None, LIMIT).action, "strip")
        self.assertEqual(plan_image(info(format="GIF"), "1:1", LIMIT).out_format, "JPEG")
        self.assertEqual(plan_image(info(format="GIF", has_alpha=True), "1:1", LIMIT).out_format, "PNG")

    def test_convert_other_formats(self):
        p = plan_image(info(format="AVIF"), None, LIMIT)
        self.assertEqual((p.action, p.out_format), ("convert", "JPEG"))
        self.assertIn("AVIF → JPEG", p.steps[0])
        self.assertEqual(plan_image(info(format="HEIC", has_alpha=True), None, LIMIT).out_format, "PNG")
        self.assertEqual(plan_image(info(format="TIFF"), None, LIMIT).out_format, "JPEG")
        self.assertEqual(plan_image(info(format="BMP"), None, LIMIT).out_format, "JPEG")

    def test_animated_rules(self):
        self.assertEqual(plan_image(info(format="GIF", is_animated=True), None, LIMIT).action, "strip")
        self.assertEqual(plan_image(info(format="GIF", is_animated=True), "1:1", LIMIT).action, "to_video")
        over = plan_image(info(format="WEBP", is_animated=True, bytes=LIMIT + 1), None, LIMIT)
        self.assertEqual((over.action, over.out_format, over.mime), ("to_video", "MP4", "video/mp4"))

    def test_over_limit_goes_to_reencode(self):
        p = plan_image(info(bytes=LIMIT + 1), None, LIMIT)
        self.assertEqual(p.action, "reencode")
        self.assertTrue(any("reduce size" in s for s in p.steps))

    def test_step_down_sequence(self):
        self.assertIsNone(step_down("JPEG", False, 8000, 100, 1000))
        self.assertEqual(step_down("PNG", False, 8000, 5000, 1000), ("convert", "JPEG"))
        self.assertEqual(step_down("PNG", True, 8000, 5000, 1000), ("resize", 6000))
        self.assertEqual(step_down("JPEG", False, 6000, 5000, 1000), ("resize", 4096))
        self.assertEqual(step_down("JPEG", False, 2048, 5000, 1000), ("fail",))

    def test_to_dict(self):
        self.assertEqual(plan_image(info(), None, LIMIT).to_dict()["action"], "strip")


if __name__ == "__main__":
    unittest.main()

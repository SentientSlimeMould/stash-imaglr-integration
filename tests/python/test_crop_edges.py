# SPDX-License-Identifier: AGPL-3.0-only
"""Edge trims for black borders: the maths, the ffmpeg cropdetect parsing, and the detector over several frames."""
import unittest
from unittest import mock

from imaglr_integration.media import ffmpeg_cmd as fc
from imaglr_integration.media import video_export
from imaglr_integration.media.ffmpeg_run import FfmpegError
from imaglr_integration.media.image_plan import plan_image

from .test_image_plan import LIMIT, info


class EdgeMathsTest(unittest.TestCase):
    def test_clean_edges_bounds_and_keeps_a_tenth(self):
        self.assertEqual(fc.clean_edges(None), {"top": 0.0, "right": 0.0, "bottom": 0.0, "left": 0.0})
        self.assertEqual(fc.clean_edges({"top": "0.2", "junk": 1})["top"], 0.2)
        self.assertEqual(fc.clean_edges({"left": 0.7})["left"], fc.MAX_EDGE)
        e = fc.clean_edges({"left": 0.45, "right": 0.45})  # together they would leave nothing
        self.assertAlmostEqual(e["left"] + e["right"], 1 - fc.MIN_KEPT, places=6)
        self.assertEqual(fc.clean_edges({"top": float("nan")})["top"], 0.0)
        self.assertFalse(fc.has_edges(fc.clean_edges({"top": 0})))
        self.assertTrue(fc.has_edges({"top": 0.01}))

    def test_edge_rect_then_aspect_inside_it(self):
        self.assertIsNone(fc.edge_rect(1920, 1080, None))
        bars = fc.edge_rect(1920, 1080, {"top": 0.1, "bottom": 0.1})
        self.assertEqual((bars.w, bars.h, bars.x, bars.y), (1920, 864, 0, 108))
        self.assertEqual(fc.compute_crop(1920, 1080, "original", 0.5, {"top": 0.1, "bottom": 0.1}), bars)
        square = fc.compute_crop(1920, 1080, "1:1", 0.5, {"top": 0.1, "bottom": 0.1})
        self.assertEqual((square.w, square.h, square.y), (864, 864, 108))
        self.assertEqual(square.x, fc.even(int(round((1920 - 864) * 0.5))))
        left = fc.compute_crop(1920, 1080, "1:1", 0.0, {"left": 0.25})  # 1440x1080 left: a 1080 square at its left edge
        self.assertEqual((left.w, left.h, left.x, left.y), (1080, 1080, 480, 0))
        self.assertEqual(fc.compute_crop(1920, 1080, "original", 0.5, {"top": 0.0}), None)

    def test_filter_chain_puts_the_trim_crop_before_the_scale(self):
        vf = fc.build_filter_chain(1920, 1080, "original", 0.5, 640, 30, edges={"left": 0.1, "right": 0.1})
        self.assertTrue(vf.startswith("crop=1536:1080:192:0,scale=640:450"), vf)
        cmd = fc.build_clip_cmd("ff", "/in", "/o.part", 0, 5, 1920, 1080, 30, edges={"top": 0.1, "bottom": 0.1})
        self.assertIn("crop=1920:864:0:108", " ".join(cmd))

    def test_plan_image_treats_trims_as_a_crop(self):
        self.assertEqual(plan_image(info(), None, LIMIT, {"top": 0.0}).action, "strip")
        p = plan_image(info(), None, LIMIT, {"top": 0.1})
        self.assertEqual(p.action, "reencode")
        self.assertIn("trim edges", p.steps)


class CropDetectTest(unittest.TestCase):
    STDERR = ("[Parsed_cropdetect_0 @ 0x1] x1:0 x2:1919 y1:139 y2:939 w:1920 h:800 x:0 y:140 pts:1 t:0.03 crop=1920:800:0:140\n"
              "[Parsed_cropdetect_0 @ 0x1] x1:0 x2:1919 y1:135 y2:943 w:1920 h:808 x:0 y:136 pts:2 t:0.07 crop=1920:808:0:136\n")

    def test_command_and_parsing(self):
        cmd = fc.build_cropdetect_cmd("ff", "http://s/stream", 12.5, headers={"ApiKey": "k"})
        s = " ".join(cmd)
        self.assertIn("-loglevel info", s)
        self.assertIn("-ss 12.500 -i http://s/stream -frames:v 12 -an -vf cropdetect=limit=24:round=2:reset=0 -f null", s)
        self.assertIn("-headers", cmd)
        r = fc.parse_cropdetect(self.STDERR)
        self.assertEqual((r.w, r.h, r.x, r.y), (1920, 808, 0, 136))  # the last line: the widest picture so far
        self.assertIsNone(fc.parse_cropdetect("nothing here"))
        self.assertIsNone(fc.parse_cropdetect("crop=0:0:0:0"))

    def test_edges_from_rect_rounds_slivers_away(self):
        e = fc.edges_from_rect(1920, 1080, fc.CropRect(1920, 808, 0, 136))
        self.assertEqual((e["left"], e["right"]), (0.0, 0.0))
        self.assertAlmostEqual(e["top"], 136 / 1080, places=3)
        self.assertAlmostEqual(e["bottom"], (1080 - 136 - 808) / 1080, places=3)
        self.assertEqual(fc.edges_from_rect(1920, 1080, fc.CropRect(1912, 1080, 4, 0))["left"], 0.0)  # under half a percent

    def test_detector_takes_the_widest_picture_across_samples(self):
        outputs = [b"crop=1920:800:0:140\n", b"crop=1920:760:0:160\n", b"", b"crop=1920:808:0:136\n"]
        calls = []

        def fake_run(cmd, timeout=60):
            calls.append(cmd)
            return b"", outputs.pop(0), 0

        with mock.patch.object(video_export, "run_capture", fake_run):
            e = video_export.detect_edges("ff", "/src.mp4", 1920, 1080, [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(len(calls), 4)
        self.assertEqual(e, fc.clean_edges({"top": 136 / 1080, "bottom": (1080 - 944) / 1080}))  # union: 0..1920 x 136..944

    def test_detector_with_no_borders_and_with_a_failing_ffmpeg(self):
        with mock.patch.object(video_export, "run_capture", lambda cmd, timeout=60: (b"", b"no crop lines", 0)):
            self.assertFalse(fc.has_edges(video_export.detect_edges("ff", "/s", 100, 100, [0.0])))
        with mock.patch.object(video_export, "run_capture", lambda cmd, timeout=60: (b"", b"boom", 1)):
            with self.assertRaises(FfmpegError):
                video_export.detect_edges("ff", "/s", 100, 100, [0.0])

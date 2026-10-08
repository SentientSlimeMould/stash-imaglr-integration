# SPDX-License-Identifier: AGPL-3.0-only
import os
import unittest

from imaglr_integration.media import ffmpeg_cmd as fc

FF = "/opt/stash/ffmpeg"


class CropScaleTest(unittest.TestCase):
    def test_compute_crop_landscape_to_portrait(self):
        r = fc.compute_crop(1920, 1080, "9:16", 0.5)
        self.assertEqual((r.w, r.h), (606, 1080))
        self.assertEqual((r.x, r.y), ((1920 - 606) // 2 // 2 * 2, 0))
        self.assertEqual(fc.compute_crop(1920, 1080, "9:16", 0.0).x, 0)
        self.assertEqual(fc.compute_crop(1920, 1080, "9:16", 1.0).x, 1920 - 606)

    def test_compute_crop_portrait_to_square(self):
        r = fc.compute_crop(1080, 1920, "1:1", 0.0)
        self.assertEqual((r.w, r.h, r.x, r.y), (1080, 1080, 0, 0))
        self.assertEqual(fc.compute_crop(1080, 1920, "1:1", 1.0).y, 840)

    def test_compute_crop_noop_cases(self):
        self.assertIsNone(fc.compute_crop(1080, 1920, "9:16", 0.5))
        self.assertIsNone(fc.compute_crop(1920, 1080, "original", 0.5))

    def test_compute_crop_odd_source_dims_are_even(self):
        r = fc.compute_crop(1079, 1919, "4:5", 0.3)
        self.assertTrue(all(v % 2 == 0 for v in (r.w, r.h, r.x, r.y)))

    def test_compute_scale_never_upscales_and_keeps_even(self):
        self.assertIsNone(fc.compute_scale(1280, 720, 1920))
        self.assertEqual(fc.compute_scale(3840, 2160, 1920), (1920, 1080))
        self.assertEqual(fc.compute_scale(1080, 2400, 1920), (864, 1920))
        self.assertEqual(fc.compute_scale(1281, 721, 1920), (1280, 720))

    def test_filter_chain_order_and_fps_cap(self):
        parts = fc.build_filter_chain(3840, 2160, "1:1", 0.5, 1920, 120).split(",")
        self.assertTrue(parts[0].startswith("crop=2160:2160:"))
        self.assertEqual(parts[1:], ["scale=1920:1920:flags=lanczos", "fps=60"])
        self.assertEqual(fc.build_filter_chain(1920, 1080, "original", 0.5, 1920, 30), "")

    def test_flip_comes_last_so_the_crop_matches_what_was_shown(self):
        self.assertEqual(fc.build_filter_chain(1920, 1080, "original", 0.5, 1920, 30, flip=True), "hflip")
        parts = fc.build_filter_chain(3840, 2160, "1:1", 0.2, 1920, 120, flip=True).split(",")
        self.assertTrue(parts[0].startswith("crop=") and parts[-1] == "hflip")
        cmd = fc.build_clip_cmd(FF, "/in", "/o", 0, 5, 1920, 1080, 30, flip=True)
        self.assertEqual(cmd[cmd.index("-vf") + 1], "hflip")


class ClipCmdTest(unittest.TestCase):
    def test_clip_cmd_structure(self):
        cmd = fc.build_clip_cmd(FF, "/in.mkv", "/out.mp4.part", 10.0, 22.5, 1920, 1080, 29.97, preset="fast", crf=18)
        s = " ".join(cmd)
        self.assertEqual(cmd[0], FF)  # the caller's binary; priority is set by ffmpeg_run, not a `nice` prefix
        self.assertIn("-progress pipe:1", s)
        # -ss before -i, then -t duration
        self.assertLess(cmd.index("-ss"), cmd.index("-i"))
        self.assertEqual(cmd[cmd.index("-ss") + 1], "10.000")
        self.assertEqual(cmd[cmd.index("-t") + 1], "12.500")
        self.assertIn("-c:v libx264 -profile:v high -preset fast -pix_fmt yuv420p -crf 18", s)
        self.assertIn("-c:a aac -b:a 128k -ar 48000 -ac 2", s)
        self.assertIn("-map_metadata -1 -map_chapters -1 -movflags +faststart -f mp4 /out.mp4.part", s)
        self.assertNotIn("-vf", cmd)  # 1080p, even, original aspect: no filter needed
        self.assertNotIn("-headers", cmd)

    def test_clip_cmd_mute_and_no_audio(self):
        cmd = fc.build_clip_cmd(FF, "/in", "/o", 0, 5, 1920, 1080, 30, mute=True)
        self.assertIn("-an", cmd)
        self.assertNotIn("aac", cmd)
        self.assertNotIn("0:a:0?", cmd)
        cmd = fc.build_clip_cmd(FF, "/in", "/o", 0, 5, 1920, 1080, 30, has_audio=False)
        self.assertIn("-an", cmd)
        self.assertNotIn("aac", cmd)

    def test_clip_cmd_crop_and_scale_in_one_chain(self):
        cmd = fc.build_clip_cmd(FF, "/in", "/o", 0, 5, 3840, 2160, 30, aspect="9:16", max_long_edge=1920)
        self.assertEqual(cmd.count("-vf"), 1)
        vf = cmd[cmd.index("-vf") + 1]
        self.assertRegex(vf, r"^crop=1214:2160:\d+:0,scale=1078:1920:flags=lanczos$")

    def test_clip_cmd_http_source_headers(self):
        cmd = fc.build_clip_cmd(FF, "http://stash/scene/1/stream", "/o", 0, 5, 1920, 1080, 30, headers={"ApiKey": "abc"})
        self.assertEqual(cmd[cmd.index("-headers") + 1], "ApiKey: abc\r\n")
        self.assertLess(cmd.index("-headers"), cmd.index("-i"))

    def test_target_kbps_and_two_pass(self):
        self.assertEqual(fc.target_kbps(500, 60.0, 128), int((500 * 8192 * 0.95) / 60 - 128))
        self.assertEqual(fc.target_kbps(1, 3600, 128), fc.MIN_KBPS)
        self.assertEqual(fc.target_kbps(500, 60.0, 128, 0.9), int(((500 * 8192 * 0.95) / 60 - 128) * 0.9))
        first, second = fc.build_two_pass_cmds(
            2000, "/tmp/log", ffmpeg=FF, src="/in", out="/o.part", in_s=0, out_s=10, width=1920, height=1080, fps=30
        )
        self.assertIn("-pass 1", " ".join(first))
        self.assertEqual(first[-3:], ["-f", "null", os.devnull])
        self.assertIn("-an", first)
        self.assertIn("-pass 2", " ".join(second))
        self.assertEqual(second[-1], "/o.part")
        self.assertIn("-b:v 2000k", " ".join(second))
        self.assertIn("-passlogfile /tmp/log", " ".join(second))
        self.assertNotIn("-crf", first)
        self.assertNotIn("-crf", second)

    def test_gif_to_mp4_cmd(self):
        v = fc.build_gif_to_mp4_cmd(FF, "/a.gif", "/a.mp4.part", width=501, height=301, fps=15)
        s = " ".join(v)
        for part in ("libx264", "-an", "+faststart", "scale=500:300", "-map_metadata -1"):
            self.assertIn(part, s)


class ImageCmdTest(unittest.TestCase):
    def test_frame_grab(self):
        g = fc.build_frame_grab_cmd(FF, "/in.mp4", "/f.jpg.part", 3.25, {"ApiKey": "k"})
        self.assertEqual(g[g.index("-ss") + 1], "3.250")
        self.assertLess(g.index("-ss"), g.index("-i"))
        self.assertIn("-frames:v", g)
        self.assertEqual(g[g.index("-q:v") + 1], "2")
        self.assertIn("-map_metadata", g)
        self.assertEqual(g[-3:], ["-f", "image2pipe", "/f.jpg.part"])

    def test_every_orientation_has_its_transform(self):
        self.assertEqual(fc.ORIENTATION_FILTERS.get(1), None)
        self.assertEqual(sorted(fc.ORIENTATION_FILTERS), [2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(fc.ORIENTATION_FILTERS[6], ["transpose=clock"])
        self.assertEqual(fc.ORIENTATION_FILTERS[8], ["transpose=cclock"])

    def test_image_cmd_rotates_explicitly_then_crops_then_scales(self):
        crop = fc.CropRect(1200, 1200, 0, 200)
        cmd = fc.build_image_cmd(FF, "/in.jpg", "/o.jpg.part", "JPEG", orientation=6, crop=crop, size=(600, 600))
        self.assertIn("-noautorotate", cmd)
        self.assertLess(cmd.index("-noautorotate"), cmd.index("-i"))
        self.assertEqual(
            cmd[cmd.index("-vf") + 1], "transpose=clock,crop=1200:1200:0:200,scale=600:600:flags=lanczos"
        )
        s = " ".join(cmd)
        self.assertIn("-map_metadata -1 -c:v mjpeg -pix_fmt yuvj420p -q:v 2 -f image2pipe /o.jpg.part", s)

    def test_image_cmd_formats(self):
        png = fc.build_image_cmd(FF, "/a", "/b", "PNG")
        self.assertNotIn("-vf", png)
        self.assertIn("png", png)
        webp = " ".join(fc.build_image_cmd(FF, "/a", "/b", "WEBP", quality=92))
        self.assertIn("-c:v libwebp -quality 92 -f webp", webp)
        auto = fc.build_image_cmd(FF, "/a.avif", "/b", "PNG", autorotate=True)
        self.assertNotIn("-noautorotate", auto)
        with self.assertRaises(ValueError):
            fc.build_image_cmd(FF, "/a", "/b", "GIF")


if __name__ == "__main__":
    unittest.main()


class BitrateBoundsTest(unittest.TestCase):
    def test_short_clips_stay_within_encoder_limits(self):
        from imaglr_integration.media import ffmpeg_cmd as fc

        self.assertEqual(fc.target_kbps(500, 3.0), fc.MAX_KBPS)

    def test_shrinking_targets_a_fraction_of_the_rejected_file(self):
        from imaglr_integration.media import ffmpeg_cmd as fc

        # a 10 MiB, 10 s file with 128 kbps audio: about 8064 kbps of video; 90 % of that
        self.assertEqual(fc.kbps_for_size(10 * 1024 * 1024, 10.0, 128, 0.9), int((8192 - 128) * 0.9))


class CodecTest(unittest.TestCase):
    """The user's codec choice in the command, and the typical-bitrate table the estimate and the export share."""

    def test_typical_bitrates(self):
        self.assertEqual(fc.typical_kbps("h264", 1920), 6000)
        self.assertEqual(fc.typical_kbps("hevc", 1920), 3600)
        self.assertEqual(fc.typical_kbps("h264", 1000), 1500)  # the next rung down
        self.assertEqual(fc.typical_kbps("h264", 320), 900)  # below the table: its smallest rung

    def test_hevc_command(self):
        cmd = fc.build_clip_cmd(FF, "/in.mkv", "/out.mp4.part", 0, 10, 1920, 1080, 30, preset="medium", codec="hevc",
                                max_long_edge=1280)
        s = " ".join(cmd)
        self.assertIn("-c:v libx265 -tag:v hvc1 -preset medium -pix_fmt yuv420p -x265-params log-level=error", s)
        self.assertNotIn("libx264", s)
        self.assertNotIn("-profile:v", s)
        self.assertIn("scale=1280:720", s)
        first, second = fc.build_two_pass_cmds(1500, "/tmp/log", ffmpeg=FF, src="/in", out="/o.part", in_s=0, out_s=10,
                                               width=1920, height=1080, fps=30, codec="hevc")
        self.assertIn("libx265", " ".join(first))
        self.assertIn("-pass 2", " ".join(second))
        self.assertIn("-b:v 1500k", " ".join(second))

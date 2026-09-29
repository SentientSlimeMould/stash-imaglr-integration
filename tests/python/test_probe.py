# SPDX-License-Identifier: AGPL-3.0-only
import unittest

from imaglr_integration.media.probe import build_probe_cmd, is_hdr, parse_probe


def probe_json(**video):
    v = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "r_frame_rate": "30000/1001",
        "avg_frame_rate": "30000/1001",
        "duration": "12.5",
        "pix_fmt": "yuv420p",
    }
    v.update(video)
    return {"streams": [v, {"codec_type": "audio", "codec_name": "aac"}], "format": {"duration": "12.5"}}


class ProbeTest(unittest.TestCase):
    def test_parse_basic(self):
        p = parse_probe(probe_json())
        self.assertEqual((p.width, p.height), (1920, 1080))
        self.assertAlmostEqual(p.fps, 29.97, delta=0.01)
        self.assertEqual(p.duration, 12.5)
        self.assertTrue(p.has_audio)
        self.assertEqual(p.audio_codec, "aac")
        self.assertFalse(is_hdr(p))
        self.assertEqual(p.display_size, (1920, 1080))
        self.assertFalse(p.has_alpha)

    def test_rotation_swaps_display_size(self):
        p = parse_probe(probe_json(side_data_list=[{"side_data_type": "Display Matrix", "rotation": -90}]))
        self.assertEqual(p.rotation, 270)
        self.assertEqual(p.display_size, (1080, 1920))
        self.assertEqual(parse_probe(probe_json(tags={"rotate": "90"})).display_size, (1080, 1920))

    def test_hdr_detection(self):
        self.assertTrue(is_hdr(parse_probe(probe_json(color_transfer="smpte2084"))))
        self.assertTrue(is_hdr(parse_probe(probe_json(color_primaries="bt2020"))))
        self.assertTrue(is_hdr(parse_probe(probe_json(side_data_list=[{"side_data_type": "Mastering display metadata"}]))))
        self.assertFalse(is_hdr(parse_probe(probe_json(color_transfer="bt709"))))

    def test_no_video_stream_raises(self):
        with self.assertRaises(ValueError):
            parse_probe({"streams": [{"codec_type": "audio"}]})

    def test_animated_webp_reports_zero_size(self):
        # What ffprobe 8 prints for an animated WebP: no size, no rates, no duration.
        data = {"streams": [{"codec_type": "video", "codec_name": "webp", "width": 0, "height": 0,
                             "r_frame_rate": "0/0", "avg_frame_rate": "0/0"}], "format": {}}
        p = parse_probe(data)
        self.assertEqual((p.width, p.height, p.fps, p.duration), (0, 0, 0.0, 0.0))

    def test_alpha_pixel_formats(self):
        for fmt in ("rgba", "yuva420p", "gbrap", "ya8", "bgra"):
            self.assertTrue(parse_probe(probe_json(pix_fmt=fmt)).has_alpha, fmt)
        for fmt in ("rgb24", "yuv420p10le", "gray", "pal8"):
            self.assertFalse(parse_probe(probe_json(pix_fmt=fmt)).has_alpha, fmt)

    def test_probe_cmd_headers(self):
        cmd = build_probe_cmd("/usr/local/bin/ffprobe", "http://s/x", {"ApiKey": "k"})
        self.assertEqual(cmd[0], "/usr/local/bin/ffprobe")
        self.assertEqual(cmd[-1], "http://s/x")
        self.assertEqual(cmd[cmd.index("-headers") + 1], "ApiKey: k\r\n")
        self.assertIn("-show_streams", cmd)


if __name__ == "__main__":
    unittest.main()

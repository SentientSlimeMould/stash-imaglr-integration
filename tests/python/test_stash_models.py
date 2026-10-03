# SPDX-License-Identifier: AGPL-3.0-only
import unittest

from imaglr_integration.stash.models import Image, Marker, Scene, Tag, VisualFile


def sample_marker(**over):
    m = {
        "id": "501",
        "title": "Great moment",
        "seconds": 10.0,
        "end_seconds": 22.5,
        "screenshot": "http://stash.test/scene/7/scene_marker/501/screenshot",
        "stream": "http://stash.test/scene/7/scene_marker/501/stream",
        "primary_tag": {"id": "10", "name": "imaglr"},
        "tags": [{"id": "20", "name": "Slow Motion"}, {"id": "21", "name": "AI_face"}],
        "scene": {
            "id": "7",
            "title": "Scene Seven",
            "date": "2024-01-01",
            "files": [
                {
                    "path": "/data/videos/seven.mp4",
                    "duration": 600.0,
                    "width": 1920,
                    "height": 1080,
                    "frame_rate": 29.97,
                    "video_codec": "h264",
                    "audio_codec": "aac",
                    "format": "mp4",
                }
            ],
            "paths": {"stream": "http://stash.test/scene/7/stream", "screenshot": "http://stash.test/scene/7/screenshot"},
            "tags": [{"id": "30", "name": "Outdoor"}, {"id": "31", "name": "slow motion"}],
            "performers": [{"name": "Alex Doe"}],
            "studio": {"name": "Studio X"},
        },
    }
    m.update(over)
    return m


def sample_image(**over):
    i = {
        "id": "801",
        "title": "Photo",
        "date": None,
        "paths": {"thumbnail": "http://stash.test/image/801/thumbnail", "image": "http://stash.test/image/801/image"},
        "visual_files": [
            {"__typename": "ImageFile", "path": "/data/pics/photo.jpg", "width": 4000, "height": 3000,
             "size": 2_000_000, "format": "mjpeg", "zip_file": None}
        ],
        "tags": [{"id": "10", "name": "imaglr"}, {"id": "40", "name": "Portrait"}],
        "performers": [{"name": "Alex Doe"}],
        "studio": None,
        "galleries": [{"id": "1", "title": "Gallery", "tags": [{"id": "41", "name": "Summer"}]}],
    }
    i.update(over)
    return i


def video_file(**over):
    f = {"__typename": "VideoFile", "path": "/data/x.mp4", "width": 480, "height": 270, "size": 1000,
         "duration": 3, "frame_rate": 10, "video_codec": "h264", "format": "mp4"}
    f.update(over)
    return f


class MarkerTest(unittest.TestCase):
    def test_parse(self):
        m = Marker.parse(sample_marker())
        self.assertEqual((m.id, m.seconds, m.end_seconds), ("501", 10.0, 22.5))
        self.assertEqual(m.primary_tag, Tag("10", "imaglr"))
        self.assertEqual(m.all_tag_ids, {"10", "20", "21"})
        self.assertEqual(m.scene.duration, 600.0)
        self.assertEqual(m.scene.performers, ["Alex Doe"])
        self.assertEqual(m.scene.studio, "Studio X")
        self.assertEqual(m.stream_url, "http://stash.test/scene/7/scene_marker/501/stream")

    def test_display_title_falls_back(self):
        self.assertEqual(Marker.parse(sample_marker(title="")).display_title, "imaglr")
        self.assertEqual(Marker.parse(sample_marker(title="", primary_tag=None)).display_title, "Marker 501")

    def test_unknown_and_missing_fields_are_tolerated(self):
        m = Marker.parse({"id": 5, "whatever": 1, "seconds": None, "end_seconds": "bad"})
        self.assertEqual((m.id, m.seconds, m.end_seconds, m.tags, m.scene), ("5", 0.0, None, [], None))


class SceneTest(unittest.TestCase):
    def test_display_title_uses_file_name(self):
        s = Scene.parse({"id": "1", "title": None, "files": [{"path": "/data/a/b.mkv"}]})
        self.assertEqual(s.display_title, "b.mkv")
        self.assertEqual(Scene.parse({"id": "2"}).display_title, "Scene 2")


class ImageTest(unittest.TestCase):
    def test_parse(self):
        i = Image.parse(sample_image())
        self.assertEqual(i.image_url, "http://stash.test/image/801/image")
        self.assertEqual(i.galleries[0].tags, [Tag("41", "Summer")])
        self.assertFalse(i.is_video)
        self.assertEqual(i.primary_file.image_format, "jpeg")  # ffmpeg-written JPEG reports "mjpeg"

    def test_first_visual_file_is_primary(self):
        files = [
            {"__typename": "ImageFile", "path": "/data/a.jpg", "format": "mjpeg"},
            {"__typename": "ImageFile", "path": "/data/z.zip/a.jpg", "format": "jpeg", "zip_file": {"path": "/data/z.zip"}},
        ]
        i = Image.parse(sample_image(visual_files=files))
        self.assertEqual(i.primary_file.path, "/data/a.jpg")
        self.assertEqual(i.files[1].zip_path, "/data/z.zip")

    def test_gif_video_file_is_an_animated_image(self):
        f = VisualFile.parse(video_file(path="/data/a.gif", format="gif", video_codec="gif"))
        self.assertFalse(f.is_video)
        self.assertTrue(f.is_animated)
        self.assertEqual(f.image_format, "gif")

    def test_real_video_file_is_a_clip(self):
        f = VisualFile.parse(video_file())
        self.assertTrue(f.is_video)
        self.assertFalse(f.is_animated)
        self.assertTrue(Image.parse(sample_image(visual_files=[video_file()])).is_video)

    def test_animated_webp_is_an_image_file(self):
        f = VisualFile.parse({"__typename": "ImageFile", "path": "/data/a.webp", "format": "webp"})
        self.assertFalse(f.is_video or f.is_animated)

    def test_format_falls_back_to_extension(self):
        self.assertEqual(VisualFile.parse({"path": "/data/A.JPG"}).image_format, "jpeg")

    def test_no_files(self):
        i = Image.parse(sample_image(visual_files=None, title=""))
        self.assertIsNone(i.primary_file)
        self.assertFalse(i.is_video)
        self.assertEqual(i.display_title, "Image 801")


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: AGPL-3.0-only
import os
import pathlib
import tempfile
import unittest

from imaglr_integration.stash.client import StashError
from imaglr_integration.stash.models import Image, Scene
from imaglr_integration.stash.paths import HttpStream, LocalFile, fetch, image_source, resolve_source, scene_source

from .test_stash_models import sample_image, sample_marker


class ResolveSourceTest(unittest.TestCase):
    def test_local_then_http(self):
        self.assertEqual(
            resolve_source("/data/a.mp4", "http://s/stream", readable=lambda p: p == "/data/a.mp4"),
            LocalFile("/data/a.mp4"),
        )
        self.assertEqual(resolve_source("/data/a.mp4", "http://s/stream", readable=lambda p: False), HttpStream("http://s/stream"))
        self.assertIsNone(resolve_source(None, None, readable=lambda p: False))

    def test_zip_member_always_uses_http(self):
        src = resolve_source("/data/z.zip/a.jpg", "http://s/image", in_zip=True, readable=lambda p: True)
        self.assertEqual(src, HttpStream("http://s/image"))

    def test_real_file_is_read_locally(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.jpg")
            pathlib.Path(path).write_bytes(b"x")
            self.assertEqual(resolve_source(path, "http://s/image"), LocalFile(path))
            self.assertEqual(resolve_source(d, "http://s/image"), HttpStream("http://s/image"))  # a folder isn't a file

    def test_scene_and_image_sources(self):
        scene = Scene.parse(sample_marker()["scene"])
        self.assertEqual(scene_source(scene), HttpStream("http://stash.test/scene/7/stream"))  # /data isn't here
        zipped = [{"__typename": "ImageFile", "path": "/data/z.zip/a.jpg", "zip_file": {"path": "/data/z.zip"}}]
        self.assertEqual(image_source(Image.parse(sample_image(visual_files=zipped))), HttpStream("http://stash.test/image/801/image"))
        self.assertIsNone(image_source(Image.parse(sample_image(visual_files=[], paths={}))))


class FetchTest(unittest.TestCase):
    """fetch() is plain urllib; file:// URLs exercise it without a network."""

    def test_download_lands_under_its_final_name(self):
        with tempfile.TemporaryDirectory() as d:
            src = pathlib.Path(d, "src.jpg")
            src.write_bytes(b"\xff\xd8data")
            dest = os.path.join(d, "out.jpg")
            content_type = fetch(src.as_uri(), dest, {"ApiKey": "k"})
            self.assertEqual(pathlib.Path(dest).read_bytes(), b"\xff\xd8data")
            self.assertEqual(content_type, "image/jpeg")
            self.assertFalse(os.path.exists(dest + ".part"))

    def test_failure_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "out.jpg")
            with self.assertRaises(StashError):
                fetch(pathlib.Path(d, "missing.jpg").as_uri(), dest, {})
            self.assertEqual(os.listdir(d), [])


if __name__ == "__main__":
    unittest.main()

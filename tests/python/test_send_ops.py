# SPDX-License-Identifier: AGPL-3.0-only
import unittest

from imaglr_integration.send_ops import _thumb, _thumb_fallback


def member(**kw):
    base = {"id": "m1", "kind": "clip", "stash_image_id": None, "stash_marker_id": None, "stash_scene_id": None,
            "source_path": None}
    return base | kw


class SentThumbnailTest(unittest.TestCase):
    def test_clip_falls_back_to_its_scene(self):
        m = member(stash_marker_id="11", stash_scene_id="2")
        self.assertEqual(_thumb(m), "scene/2/scene_marker/11/screenshot")
        self.assertEqual(_thumb_fallback(m), "scene/2/screenshot")

    def test_image_has_no_fallback(self):
        m = member(kind="image", stash_image_id="5")
        self.assertEqual(_thumb(m), "image/5/thumbnail")
        self.assertIsNone(_thumb_fallback(m))

    def test_nothing_known(self):
        self.assertIsNone(_thumb(member()))
        self.assertIsNone(_thumb_fallback(member()))

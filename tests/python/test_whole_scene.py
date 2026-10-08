# SPDX-License-Identifier: AGPL-3.0-only
"""Sharing a whole scene without a marker: the item, its card, the queue listing, removal, the send's source and
tag swap. Stash is faked at the api layer."""
import os
import tempfile
import unittest
from unittest import mock

from imaglr_integration import items, jobs, queue_ops, services
from imaglr_integration.context import Context, UserError
from imaglr_integration.db import Database
from imaglr_integration.settings import Settings
from imaglr_integration.stash import Scene, Tag

from .test_stash_models import sample_marker

QUEUE, DONE = Tag("10", "imaglr"), Tag("11", "imaglr-sent")


def sample_scene(**over):
    d = dict(sample_marker()["scene"])
    d["paths"] = {"stream": "http://stash.test/scene/7/stream", "screenshot": "http://stash.test/scene/7/screenshot",
                  "preview": "http://stash.test/scene/7/preview"}
    d["tags"] = [{"id": "10", "name": "imaglr"}, {"id": "30", "name": "Beach"}]
    d["performers"] = [{"name": "Alex Doe"}]
    d["studio"] = {"name": "Studio X"}
    d.update(over)
    return Scene.parse(d)


class WholeSceneItemTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)

    def test_item_spans_the_scene_up_to_the_limit_with_its_tags(self):
        item = services.item_from_scene(self.db, Settings(), sample_scene())
        self.assertEqual((item["kind"], item["stash_scene_id"], item["stash_marker_id"]), ("clip", "7", None))
        self.assertEqual((item["in_s"], item["out_s"]), (0.0, 600.0))
        self.assertIn("beach", item["tags"])
        self.assertIn("alex doe", item["tags"])
        self.assertNotIn("imaglr", item["tags"])  # the workflow tag is never suggested
        again = services.item_from_scene(self.db, Settings(), sample_scene())
        self.assertEqual(again["id"], item["id"])  # reused, not duplicated
        long_scene = sample_scene(id="8", files=[{**sample_marker()["scene"]["files"][0], "duration": 5000.0}])
        self.assertEqual(services.item_from_scene(self.db, Settings(), long_scene)["out_s"], services.MAX_CLIP_SECONDS)

    def test_a_marker_clip_on_the_same_scene_is_a_different_item(self):
        scene = sample_scene()
        whole = services.item_from_scene(self.db, Settings(), scene)
        marker_item = items.create_item(self.db, kind="clip", stash_marker_id="501", stash_scene_id="7", source_title="m",
                                        in_s=10.0, out_s=22.5)
        self.assertEqual(items.active_for_scene(self.db, "7")["id"], whole["id"])
        self.assertNotEqual(items.active_for_marker(self.db, "501")["id"], whole["id"])
        self.assertEqual(marker_item["stash_scene_id"], "7")

    def test_card_comes_from_the_scene(self):
        scene = sample_scene()
        item = services.item_from_scene(self.db, Settings(), scene)
        card = services.clip_card(item, None, None, scene=scene)
        self.assertTrue(card["whole_scene"])
        self.assertEqual(card["thumb"], "scene/7/screenshot")
        self.assertEqual(card["preview"], "scene/7/preview")
        self.assertEqual((card["width"], card["height"], card["duration"], card["scene_duration"]), (1920, 1080, 600.0, 600.0))
        self.assertEqual(card["tab"], "clips")


class FakeStash:
    def gql(self, query, variables=None):
        assert "configuration" in query, query
        return {"configuration": {"plugins": {"imaglrIntegration": {}}}}


class WholeSceneOpsTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.ctx = Context({"args": {"mode": "queue"}})
        self.ctx._db = self.db
        self.ctx._stash = FakeStash()
        self.calls = []

    def patched(self, scenes=(), markers=(), images=()):
        rec = lambda name: (lambda *a, **k: self.calls.append((name, a[1:])))  # noqa: E731
        return [
            mock.patch.object(queue_ops.api, "workflow_tags", lambda s, q, d: (QUEUE, DONE)),
            mock.patch.object(queue_ops.api, "queued_markers", lambda s, t: list(markers)),
            mock.patch.object(queue_ops.api, "queued_scenes", lambda s, t: list(scenes)),
            mock.patch.object(queue_ops.api, "queued_images", lambda s, t: list(images)),
            mock.patch.object(queue_ops.api, "scenes_remove_tags", rec("scenes_remove_tags")),
            mock.patch.object(queue_ops.api, "scenes_add_tags", rec("scenes_add_tags")),
            mock.patch.object(queue_ops.api, "images_remove_tags", rec("images_remove_tags")),
            mock.patch.object(queue_ops.api, "find_scene", lambda s, i: sample_scene() if i == "7" else None),
        ]

    def run_with(self, patches, fn):
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return fn()

    def test_queue_lists_a_tagged_scene_as_a_whole_scene_clip(self):
        out = self.run_with(self.patched(scenes=[sample_scene()]), lambda: queue_ops.op_queue(self.ctx))
        cards = out["items"]
        self.assertEqual(len(cards), 1)
        self.assertTrue(cards[0]["whole_scene"])
        self.assertEqual(cards[0]["title"], "Scene Seven")
        ctx = Context({"args": {"mode": "item_detail", "item_id": cards[0]["id"]}})
        ctx._db, ctx._stash = self.db, FakeStash()
        detail = queue_ops.op_item_detail(ctx)
        self.assertTrue(detail["files"][0]["whole_scene"])
        self.assertEqual(detail["files"][0]["stash_scene_id"], "7")
        self.assertIn("beach", [t["tag"] for t in detail["suggestions"]["active"]])

    def test_removing_a_whole_scene_untags_the_scene(self):
        out = self.run_with(self.patched(scenes=[sample_scene()]), lambda: queue_ops.op_queue(self.ctx))
        item_id = out["items"][0]["id"]
        self.ctx = Context({"args": {"mode": "remove_from_queue", "item_id": item_id}})
        self.ctx._db, self.ctx._stash = self.db, FakeStash()
        self.assertEqual(queue_ops.op_remove_from_queue(self.ctx), {"removed": 1})
        self.assertIn(("scenes_remove_tags", (["7"], ["10"])), self.calls)
        self.assertIsNone(items.get_item(self.db, item_id))

    def test_add_scenes_tags_them(self):
        self.ctx = Context({"args": {"mode": "add_scenes", "scene_ids": ["7", "8"]}})
        self.ctx._db, self.ctx._stash = self.db, FakeStash()
        out = self.run_with(self.patched(), lambda: queue_ops.op_add_scenes(self.ctx))
        self.assertEqual(out, {"added": 2, "tag": "imaglr"})
        self.assertIn(("scenes_add_tags", (["7", "8"], ["10"])), self.calls)
        with self.assertRaises(UserError):
            queue_ops.op_add_scenes(Context({"args": {"mode": "add_scenes", "scene_ids": []}}))


class WholeSceneSendTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.ctx = Context({"args": {"mode": "task_send"}})
        self.ctx._db = self.db
        self.ctx._stash = FakeStash()

    def test_source_is_the_scene_file_and_the_swap_is_on_the_scene(self):
        item = services.item_from_scene(self.db, Settings(), sample_scene())
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"x")
        self.addCleanup(os.remove, f.name)
        scene = sample_scene(files=[{**sample_marker()["scene"]["files"][0], "path": f.name}])
        with mock.patch.object(jobs.api, "find_scene", lambda s, i: scene):
            src, headers = jobs.clip_source(self.ctx, item)
        self.assertEqual((src, headers), (f.name, None))
        swapped = []
        with mock.patch.object(jobs.api, "scene_swap_tags", lambda s, sid, q, d: swapped.append((sid, q.name, d.name))):
            failed = jobs.swap_source_tags(self.ctx, [item], QUEUE, DONE)
        self.assertEqual((failed, swapped), ([], [("7", "imaglr", "imaglr-sent")]))
        self.assertFalse(items.get_item(self.db, item["id"])["tags_pending"])

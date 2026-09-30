# SPDX-License-Identifier: AGPL-3.0-only
"""The send task (jobs.run_send) end to end against a fake Stash and a fake imaglr client: prepare → draft →
follow-up → tag swap, and every way it can fail. Uses a real JPEG so the image path needs no ffmpeg."""
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

from imaglr_integration import blogs, items, jobs, log, services
from imaglr_integration.context import Context
from imaglr_integration.imaglr import DraftResult, ImaglrError
from imaglr_integration.media.ffmpeg_run import FfmpegError
from imaglr_integration.settings import Settings
from imaglr_integration.stash import Image, StashError, Tag
from imaglr_integration.stash.paths import without_apikey

from .media_fixtures import JPEG_16x8

QUEUE, DONE = Tag("10", "imaglr"), Tag("11", "imaglr-sent")


class FakeImaglr:
    def __init__(self, fail=None, follow_up_fail=None, returned_tags=None):
        self.fail, self.follow_up_fail, self.returned_tags = fail, follow_up_fail, returned_tags
        self.calls = []

    def create_draft(self, files, tags=(), body_html=None, progress_cb=None):
        self.calls.append(("create_draft", [os.path.basename(f[0]) for f in files], list(tags), body_html))
        if self.fail:
            raise self.fail
        return DraftResult("d1", "https://imaglr.example/p/d1", list(tags) if self.returned_tags is None else self.returned_tags)

    def queue_draft(self, draft_id):
        self.calls.append(("queue", draft_id))
        if self.follow_up_fail:
            raise self.follow_up_fail
        return {}

    def publish_draft(self, draft_id):
        self.calls.append(("publish", draft_id))
        if self.follow_up_fail:
            raise self.follow_up_fail
        return {}


class SendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.jpeg = os.path.join(self.tmp.name, "photo.jpg")
        with open(self.jpeg, "wb") as f:
            f.write(JPEG_16x8)
        self.ctx = Context({"args": {"mode": "task_send"}, "server_connection": {"PluginDir": self.tmp.name}})
        self.addCleanup(self.ctx.close)
        self.db = self.ctx.db
        self.blog = blogs.add_blog(self.db, "pbk_one|secret123")
        blogs.record_check(self.db, self.blog["id"], {"name": "myblog", "supporter": True}, None)
        self.swaps = []
        self.stderr = io.StringIO()

    def image(self, **over):
        d = {"id": "801", "title": "Photo", "paths": {"thumbnail": "t", "image": "http://stash/image/801/image"},
             "visual_files": [{"__typename": "ImageFile", "path": self.jpeg, "width": 16, "height": 8, "size": 1000, "format": "jpeg"}],
             "tags": [{"id": "10", "name": "imaglr"}, {"id": "40", "name": "Portrait"}], "performers": [], "studio": None, "galleries": []}
        d.update(over)
        return Image.parse(d)

    def queued_image_item(self, **fields):
        return services.item_from_image(self.db, Settings(), self.image()) if not fields else items.create_item(self.db, **fields)

    def send(self, item_id, client=None, tools=("/nonexistent/ffmpeg", "/nonexistent/ffprobe"), swap=None, settings=None,
            find_image=None):
        client = client or FakeImaglr()

        def record_swap(stash, image_id, q, d):
            self.swaps.append(image_id)
            if swap:
                swap()

        with mock.patch.object(jobs.plugin_settings, "load", lambda s: settings or Settings()), \
             mock.patch.object(jobs.api, "workflow_tags", lambda s, q, d: (QUEUE, DONE)), \
             mock.patch.object(jobs, "media_tools", lambda c: tools), \
             mock.patch.object(jobs.api, "find_image", find_image or (lambda s, i: self.image())), \
             mock.patch.object(jobs.api, "image_swap_tags", record_swap), \
             mock.patch.object(services.api, "find_image", find_image or (lambda s, i: self.image())), \
             mock.patch.object(Context, "imaglr", lambda self_, b: client), \
             redirect_stderr(self.stderr):
            jobs.run_send(self.ctx, item_id)
        return items.get_item(self.db, item_id), client

    # ---- the happy paths ------------------------------------------------------------------------

    def test_draft_is_saved_and_the_stash_tags_swapped(self):
        item = self.queued_image_item()
        item, client = self.send(item["id"])
        self.assertEqual((item["status"], item["sent_as"], item["draft_id"]), ("sent", "draft", "d1"))
        self.assertEqual(client.calls[0][:3], ("create_draft", ["photo.jpg"], ["portrait"]))
        self.assertTrue(os.path.isfile(item["output_path"]))
        self.assertEqual(self.swaps, ["801"])
        self.assertIsNone(item["error_code"])

    def test_publish_follow_up(self):
        item = self.queued_image_item()
        items.update_item(self.db, item["id"], action="publish")
        item, client = self.send(item["id"])
        self.assertEqual(item["sent_as"], "publish")
        self.assertEqual(client.calls[-1], ("publish", "d1"))

    def test_failed_follow_up_keeps_the_draft_and_offers_retry(self):
        item = self.queued_image_item()
        items.update_item(self.db, item["id"], action="queue")
        item, _ = self.send(item["id"], FakeImaglr(follow_up_fail=ImaglrError("server_error", "boom", http_status=500)))
        self.assertEqual((item["status"], item["sent_as"], item["followup_failed"]), ("sent", "draft", True))
        self.assertIn("adding it to your imaglr queue failed", item["error_detail"])

    def test_tags_dropped_by_imaglr_are_recorded(self):
        item = self.queued_image_item()
        # imaglr echoes the tags it kept; an empty list means "no tag info" and drops nothing
        item, _ = self.send(item["id"], FakeImaglr(returned_tags=["other"]))
        self.assertEqual(item["dropped_tags"], ["portrait"])

    def test_automatic_tags_are_refreshed_before_sending(self):
        # A rule added after the item was queued applies to the upload (0.1.10 promise; broken until 0.1.11).
        item = self.queued_image_item()
        self.assertEqual(item["tags"], ["portrait"])
        self.db.execute("INSERT INTO tag_rules(stash_tag, imaglr_tags, created_at, updated_at) VALUES('Portrait', '[\"people\"]', 'x', 'x')")
        item, client = self.send(item["id"])
        self.assertEqual(client.calls[0][2], ["people"])
        self.assertEqual(item["tags"], ["people"])

    def test_edited_tags_are_sent_as_edited(self):
        item = self.queued_image_item()
        items.update_item(self.db, item["id"], tags=["mine"], tags_auto=False)
        self.db.execute("INSERT INTO tag_rules(stash_tag, imaglr_tags, created_at, updated_at) VALUES('Portrait', '[\"people\"]', 'x', 'x')")
        _, client = self.send(item["id"])
        self.assertEqual(client.calls[0][2], ["mine"])

    # ---- failures before the draft exists -------------------------------------------------------

    def test_no_blog(self):
        blogs.remove_blog(self.db, self.blog["id"])
        item = self.queued_image_item()
        item, client = self.send(item["id"])
        self.assertEqual((item["status"], item["error_code"]), ("ready", "no_blog"))
        self.assertEqual(client.calls, [])

    def test_source_deleted(self):
        item = self.queued_image_item()
        item, _ = self.send(item["id"], find_image=lambda s, i: None)
        self.assertEqual((item["status"], item["error_code"]), ("failed", "source_deleted"))

    def test_upload_error_is_explained(self):
        item = self.queued_image_item()
        item, _ = self.send(item["id"], FakeImaglr(fail=ImaglrError("invalid_key", "nope", http_status=401)))
        self.assertEqual((item["status"], item["error_code"]), ("failed", "invalid_key"))
        self.assertIn("no longer accepts the key", item["error_detail"])
        self.assertEqual(self.swaps, [])

    def test_too_large_with_no_clip_to_shrink_fails_cleanly(self):
        item = self.queued_image_item()
        item, client = self.send(item["id"], FakeImaglr(fail=ImaglrError("file_too_large", "too big", http_status=413)))
        self.assertEqual((item["status"], item["error_code"]), ("failed", "file_too_large"))
        self.assertEqual(len(client.calls), 1)

    def test_unexpected_exception_is_recorded_not_left_busy(self):
        item = self.queued_image_item()
        # crop forces a re-encode through the (missing) ffmpeg: FileNotFoundError, not a JobFailed
        items.update_item(self.db, item["id"], crop={"aspect": "1:1", "position": 0.5})
        item, client = self.send(item["id"])
        self.assertEqual((item["status"], item["error_code"]), ("failed", "unexpected"))
        self.assertIn("FileNotFoundError", item["error_detail"])
        self.assertIn("Traceback", self.stderr.getvalue())
        self.assertEqual(client.calls, [])

    def test_stash_error_before_the_draft(self):
        item = self.queued_image_item()

        def broken(s, i):
            raise StashError("Stash returned HTTP 500")

        item, _ = self.send(item["id"], find_image=broken)
        self.assertEqual((item["status"], item["error_code"]), ("failed", "stash_error"))

    # ---- after the draft exists ------------------------------------------------------------------

    def test_tag_swap_failure_is_reported_and_the_item_stays_sent(self):
        item = self.queued_image_item()

        def fail():
            raise StashError("tag update failed")

        item, _ = self.send(item["id"], swap=fail)
        self.assertEqual((item["status"], item["error_code"]), ("sent", "tag_swap_failed"))
        self.assertIn("Photo", item["error_detail"])

    def test_exception_after_the_draft_still_marks_the_item_sent(self):
        item = self.queued_image_item()

        def boom():
            raise RuntimeError("cleanup exploded")

        with mock.patch.object(jobs, "cleanup_prepared", lambda *a: boom()):
            item, _ = self.send(item["id"])
        self.assertEqual((item["status"], item["draft_id"], item["error_code"]), ("sent", "d1", "unexpected"))
        self.assertIn("cleanup exploded", item["error_detail"])

    def test_already_sent_items_are_not_sent_again(self):
        item = self.queued_image_item()
        items.update_item(self.db, item["id"], status="sent")
        _, client = self.send(item["id"])
        self.assertEqual(client.calls, [])


class RedactionTest(unittest.TestCase):
    """Stash's API key must not reach the card, the log or the reply via ffmpeg's error output."""

    def tearDown(self):
        log._SECRETS.clear()

    def test_job_failed_detail_is_redacted(self):
        log.register_secret("STASHKEY1234567890")
        err = FfmpegError("ffmpeg failed", 1, "http://stash/scene/1/stream?apikey=STASHKEY1234567890: Connection refused")
        failed = jobs.JobFailed("ffmpeg_failed", f"clip: {err}")
        self.assertNotIn("STASHKEY1234567890", failed.detail)
        self.assertIn("apikey=***", failed.detail)

    def test_stream_urls_lose_the_api_key(self):
        self.assertEqual(without_apikey("http://s/scene/1/stream?apikey=abc&start=2"), "http://s/scene/1/stream?start=2")
        self.assertEqual(without_apikey("http://s/scene/1/stream"), "http://s/scene/1/stream")

    def test_imaglr_keys_are_still_masked(self):
        self.assertEqual(log.redact("key pbk_abc|secret failed"), "key pbk_*** failed")


if __name__ == "__main__":
    unittest.main()

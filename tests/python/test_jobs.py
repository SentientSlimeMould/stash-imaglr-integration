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
from imaglr_integration.context import Context, UserError
from imaglr_integration.imaglr import DraftResult, ImaglrError, UploadCancelled
from imaglr_integration.media.ffmpeg_run import FfmpegError
from imaglr_integration.settings import Settings
from imaglr_integration.stash import Image, StashError, Tag
from imaglr_integration.stash.paths import without_apikey

from .media_fixtures import JPEG_16x8

QUEUE, DONE = Tag("10", "imaglr"), Tag("11", "imaglr-sent")


class FakeImaglr:
    def __init__(self, fail=None, follow_up_fail=None, returned_tags=None, during_upload=None):
        self.fail, self.follow_up_fail, self.returned_tags = fail, follow_up_fail, returned_tags
        self.during_upload = during_upload  # called once the body is being streamed (e.g. the user presses Stop)
        self.calls = []

    def create_draft(self, files, tags=(), body_html=None, progress_cb=None, should_cancel=None):
        self.calls.append(("create_draft", [os.path.basename(f[0]) for f in files], list(tags), body_html))
        if self.during_upload:
            self.during_upload()
        if should_cancel and should_cancel():
            raise UploadCancelled()
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


class SendHarness(unittest.TestCase):
    """A send task against a fake Stash and a fake imaglr; subclasses hold the cases."""

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
            find_image=None, action=None, mark=True):
        client = client or FakeImaglr()
        if mark:  # what the send operation does before queueing the task
            items.update_item(self.db, item_id, status="exporting")

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
            jobs.run_send(self.ctx, item_id, action)
        return items.get_item(self.db, item_id), client



class SendTest(SendHarness):
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
        self.assertTrue(item["tags_pending"])

    def test_exception_after_the_draft_still_marks_the_item_sent(self):
        item = self.queued_image_item()

        def boom():
            raise RuntimeError("cleanup exploded")

        with mock.patch.object(jobs, "cleanup_prepared", lambda *a: boom()):
            item, _ = self.send(item["id"])
        self.assertEqual((item["status"], item["draft_id"], item["error_code"]), ("sent", "d1", "unexpected"))
        self.assertIn("cleanup exploded", item["error_detail"])

    def test_only_items_marked_by_the_send_operation_run(self):
        # A task that starts for an item no longer "exporting" (already sent, cancelled, or never queued) does nothing.
        item = self.queued_image_item()
        for status in ("sent", "pending", "ready", "failed"):
            items.update_item(self.db, item["id"], status=status)
            _, client = self.send(item["id"], mark=False)
            self.assertEqual(client.calls, [], status)

    def test_send_all_downgrade_does_not_change_the_item_setting(self):
        item = self.queued_image_item()
        items.update_item(self.db, item["id"], action="publish")
        item, client = self.send(item["id"], action="draft")
        self.assertEqual((item["sent_as"], item["action"]), ("draft", "publish"))
        self.assertEqual([c[0] for c in client.calls], ["create_draft"])

    def test_stop_during_the_upload_creates_no_draft(self):
        item = self.queued_image_item()
        press_stop = lambda: items.update_item(self.db, item["id"], cancel_requested=True)
        item, client = self.send(item["id"], FakeImaglr(during_upload=press_stop))
        self.assertEqual((item["error_code"], item["draft_id"]), ("cancelled", None))
        self.assertIn(item["status"], ("pending", "ready"))
        self.assertEqual(len(client.calls), 1)  # the upload started and was aborted from inside the body

    def test_no_retry_once_the_body_was_sent(self):
        item = self.queued_image_item()
        lost = ImaglrError("network_error", "timed out")
        lost.body_sent = True
        item, client = self.send(item["id"], FakeImaglr(fail=lost))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(item["status"], "failed")
        self.assertIn("check your imaglr drafts", item["error_detail"])

    def test_transient_error_before_the_body_is_retried(self):
        item = self.queued_image_item()
        client = FakeImaglr(fail=ImaglrError("server_error", "boom", http_status=500))
        with mock.patch.object(jobs.time, "sleep", lambda s: None):
            item, client = self.send(item["id"], client)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(item["status"], "failed")

    def test_pending_tag_swap_is_retried_from_the_queue_instead_of_requeueing(self):
        from imaglr_integration import queue_ops

        item = self.queued_image_item()

        def fail():
            raise StashError("tag update failed")

        item, _ = self.send(item["id"], swap=fail)
        self.assertTrue(item["tags_pending"])
        self.assertEqual(item["error_code"], "tag_swap_failed")
        # the queue sees the image still tagged: it retries the swap rather than creating a new item
        self.swaps.clear()
        with mock.patch.object(jobs.api, "image_swap_tags", lambda s, i, q, d: self.swaps.append(i)):
            skipped = queue_ops._retry_pending_swap(self.ctx, (QUEUE, DONE), image_id="801")
        self.assertTrue(skipped)
        self.assertEqual(self.swaps, ["801"])
        after = items.get_item(self.db, item["id"])
        self.assertFalse(after["tags_pending"])
        self.assertIsNone(after["error_code"])
        self.assertIsNone(items.active_for_image(self.db, "801"))


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


class GifTest(unittest.TestCase):
    """The GIF ladder (export_gif) with a fake ffmpeg that writes files of chosen sizes, and the send task's
    handling of a GIF that won't fit."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def fake_ffmpeg(self, sizes):
        """run_ffmpeg stand-in: each call writes the next size from `sizes` to the command's output file."""
        from imaglr_integration.media import video_export
        sizes = list(sizes)
        calls = []

        def run(cmd, output=None, **kw):
            calls.append(cmd)
            if output.endswith("thumb.jpg"):
                with open(output, "wb") as f:
                    f.write(b"j")
                return
            with open(output, "wb") as f:
                f.write(b"x" * sizes.pop(0))

        from imaglr_integration.media.probe import ProbeInfo
        info = mock.Mock(spec=ProbeInfo)
        info.display_size = (1920, 1080)
        return mock.patch.object(video_export, "run_ffmpeg", run), mock.patch.object(video_export, "probe", lambda *a: info), calls

    def test_ladder_stops_at_the_first_rung_under_target(self):
        from imaglr_integration.media.video_export import VideoSettings, export_gif

        run_patch, probe_patch, calls = self.fake_ffmpeg([5000, 3000, 1500])
        with run_patch, probe_patch:
            r = export_gif("/src.mp4", self.tmp.name, title="t", in_s=0, out_s=8, settings=VideoSettings("ff", "fp"),
                           target_bytes=2000, limit_bytes=10000)
        self.assertEqual(r.bytes, 1500)
        self.assertEqual(r.note, "GIF · 0.0 MB · 480 px wide · 12 fps")
        self.assertEqual(len([c for c in calls if "-loop" in c]), 3)
        self.assertTrue(r.path.endswith(".gif"))

    def test_a_chosen_width_starts_the_ladder_there(self):
        from imaglr_integration.media.video_export import VideoSettings, export_gif

        run_patch, probe_patch, calls = self.fake_ffmpeg([1500])
        with run_patch, probe_patch:
            r = export_gif("/src.mp4", self.tmp.name, title="t", in_s=0, out_s=8, settings=VideoSettings("ff", "fp"),
                           target_bytes=2000, limit_bytes=10000, max_width=480)
        self.assertEqual(r.note, "GIF · 0.0 MB · 480 px wide · 12 fps")
        self.assertEqual(len([c for c in calls if "-loop" in c]), 1)  # straight to the 480 rung

    def test_bottom_rung_is_accepted_up_to_the_hard_limit(self):
        from imaglr_integration.media.video_export import VideoSettings, export_gif

        run_patch, probe_patch, calls = self.fake_ffmpeg([9000, 8000, 7000, 6000, 5000])
        with run_patch, probe_patch:
            r = export_gif("/src.mp4", self.tmp.name, title="t", in_s=0, out_s=8, settings=VideoSettings("ff", "fp"),
                           target_bytes=2000, limit_bytes=5500)
        self.assertEqual((r.bytes, r.note), (5000, "GIF · 0.0 MB · 320 px wide · 8 fps"))

    def test_too_large_even_at_the_bottom_says_how_short_it_must_be(self):
        from imaglr_integration.media.video_export import GifTooLarge, VideoSettings, export_gif

        run_patch, probe_patch, _ = self.fake_ffmpeg([9000, 8000, 7000, 6000, 5000])
        with run_patch, probe_patch, self.assertRaises(GifTooLarge) as cm:
            export_gif("/src.mp4", self.tmp.name, title="t", in_s=0, out_s=10, settings=VideoSettings("ff", "fp"),
                       target_bytes=2000, limit_bytes=2500)
        self.assertEqual(cm.exception.size, 5000)
        self.assertAlmostEqual(cm.exception.fit_seconds, 10 * 2500 * 0.9 / 5000, places=3)
        self.assertEqual(glob_parts(self.tmp.name), [])

    def test_gif_command_shape(self):
        from imaglr_integration.media import ffmpeg_cmd as fc

        cmd = fc.build_gif_cmd("ff", "/in.mp4", "/o.gif.part", 2, 6, 1920, 1080, long_edge=480, gif_fps=10, colors=64, flip=True)
        vf = cmd[cmd.index("-filter_complex") + 1]
        self.assertTrue(vf.startswith("fps=10,"))
        self.assertIn("scale=480:270", vf)
        self.assertIn("hflip,split", vf)
        self.assertIn("max_colors=64", vf)
        self.assertIn("-an", cmd)
        self.assertEqual(cmd[-3:], ["-f", "gif", "/o.gif.part"])
        self.assertNotIn("reverse", vf)
        boom = fc.build_gif_cmd("ff", "/in.mp4", "/o.gif.part", 2, 6, 1920, 1080, long_edge=480, gif_fps=10, colors=64, loop="boomerang")
        bvf = boom[boom.index("-filter_complex") + 1]
        self.assertIn("split[f][r];[r]reverse,trim=start_frame=1[rv];[f][rv]concat=n=2:v=1:a=0,split[a][b]", bvf)

    def test_gif_rungs_are_widths_and_portrait_gets_the_taller_cap(self):
        from imaglr_integration.media import ffmpeg_cmd as fc

        self.assertEqual(fc.GIF_LADDER[0][0], 698)  # imaglr's feed width
        self.assertEqual(fc.gif_long_edge_cap(1920, 1080, "original", 0.5, 698), 698)
        self.assertEqual(fc.gif_long_edge_cap(1080, 1920, "original", 0.5, 698), round(698 * 1920 / 1080))
        # cropped to a portrait preset, a landscape source is treated as the portrait it becomes
        self.assertEqual(fc.gif_long_edge_cap(1920, 1080, "9:16", 0.5, 698), round(698 * 1080 / 606))


def glob_parts(folder):
    import glob
    return glob.glob(os.path.join(folder, "*.part"))


class GifSendTest(SendHarness):
    """run_send with a GIF clip: the ladder's result, the fallback to video, and Send all's override."""

    def clip_item(self, fmt="gif"):
        return items.create_item(self.db, kind="clip", stash_image_id="801", source_title="Clip", in_s=0.0, out_s=5.0, format=fmt)

    def send_clip(self, item_id, gif_result=None, gif_error=None, **kw):
        from imaglr_integration.media.video_export import ExportResult

        def fake_export_gif(src, out_dir, **a):
            if gif_error:
                raise gif_error
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, "c.gif")
            with open(path, "wb") as f:
                f.write(b"g" * 100)
            return gif_result or ExportResult(path, 100, 480, 270, False, None, "GIF · 0.0 MB · 480 px wide · 12 fps")

        def fake_export_clip(src, out_dir, **a):
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, "c.mp4")
            with open(path, "wb") as f:
                f.write(b"v" * 100)
            return ExportResult(path, 100, 1920, 1080, False, None)

        with mock.patch.object(jobs, "export_gif", fake_export_gif), mock.patch.object(jobs, "export_clip", fake_export_clip), \
             mock.patch.object(jobs, "clip_source", lambda c, m: ("/src.mp4", None)):
            return self.send(item_id, **kw)

    def test_gif_clip_is_uploaded_as_a_gif_with_its_note(self):
        item = self.clip_item()
        item, client = self.send_clip(item["id"])
        self.assertEqual(item["status"], "sent")
        self.assertEqual(client.calls[0][1], ["c.gif"])
        self.assertEqual(item["output_note"], "GIF · 0.0 MB · 480 px wide · 12 fps")
        self.assertEqual(item["output_mime"], "image/gif")

    def test_gif_that_cannot_fit_fails_with_advice(self):
        from imaglr_integration.media.video_export import GifTooLarge

        item = self.clip_item()
        item, client = self.send_clip(item["id"], gif_error=GifTooLarge(52 * 1048576, 38 * 1048576, 11.2))
        self.assertEqual((item["status"], item["error_code"]), ("failed", "gif_too_large"))
        self.assertEqual(item["error_detail"], "This GIF is too big even at its smallest (52 MB; the limit is 40). Trim it to about 11 seconds, or send it as a video.")
        self.assertEqual(client.calls, [])

    def test_gif_fallback_sends_a_video_and_says_so(self):
        from imaglr_integration.media.video_export import GifTooLarge

        item = self.clip_item()
        with mock.patch.object(jobs, "run_send", wraps=jobs.run_send) as _:
            pass
        item, client = self.send_clip(item["id"], gif_error=GifTooLarge(52 * 1048576, 38 * 1048576, 11.2), action=None)
        self.assertEqual(item["status"], "failed")  # without the fallback flag
        item2 = self.clip_item()

        def fake_gif_fallback(*a, **kw):
            raise GifTooLarge(52 * 1048576, 38 * 1048576, 11.2)

        from imaglr_integration.media.video_export import ExportResult
        with mock.patch.object(jobs, "export_gif", fake_gif_fallback), \
             mock.patch.object(jobs, "export_clip", lambda src, out_dir, **a: self._video(out_dir)), \
             mock.patch.object(jobs, "clip_source", lambda c, m: ("/src.mp4", None)):
            items.update_item(self.db, item2["id"], status="exporting")
            with mock.patch.object(jobs.plugin_settings, "load", lambda s: Settings()), \
                 mock.patch.object(jobs.api, "workflow_tags", lambda s, q, d: (QUEUE, DONE)), \
                 mock.patch.object(jobs, "media_tools", lambda c: ("ff", "fp")), \
                 mock.patch.object(jobs.api, "image_swap_tags", lambda *a: None), \
                 mock.patch.object(services.api, "find_image", lambda s, i: self.image()), \
                 mock.patch.object(Context, "imaglr", lambda self_, b: FakeImaglr()), \
                 redirect_stderr(self.stderr):
                jobs.run_send(self.ctx, item2["id"], None, gif_fallback=True)
        sent = items.get_item(self.db, item2["id"])
        self.assertEqual((sent["status"], sent["format"], sent["output_mime"]), ("sent", "video", "video/mp4"))
        self.assertEqual(sent["output_note"], jobs.GIF_FALLBACK_NOTE)

    def _video(self, out_dir):
        from imaglr_integration.media.video_export import ExportResult
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "c.mp4")
        with open(path, "wb") as f:
            f.write(b"v" * 100)
        return ExportResult(path, 100, 1920, 1080, False, None)

    def test_format_override_sends_a_gif_clip_as_video_without_changing_it(self):
        item = self.clip_item()
        from imaglr_integration.media.video_export import ExportResult
        with mock.patch.object(jobs, "export_gif", lambda *a, **k: self.fail("GIF export must not run")), \
             mock.patch.object(jobs, "export_clip", lambda src, out_dir, **a: self._video(out_dir)), \
             mock.patch.object(jobs, "clip_source", lambda c, m: ("/src.mp4", None)):
            items.update_item(self.db, item["id"], status="exporting")
            with mock.patch.object(jobs.plugin_settings, "load", lambda s: Settings()), \
                 mock.patch.object(jobs.api, "workflow_tags", lambda s, q, d: (QUEUE, DONE)), \
                 mock.patch.object(jobs, "media_tools", lambda c: ("ff", "fp")), \
                 mock.patch.object(jobs.api, "image_swap_tags", lambda *a: None), \
                 mock.patch.object(services.api, "find_image", lambda s, i: self.image()), \
                 mock.patch.object(Context, "imaglr", lambda self_, b: FakeImaglr()), \
                 redirect_stderr(self.stderr):
                jobs.run_send(self.ctx, item["id"], None, format_override="video")
        sent = items.get_item(self.db, item["id"])
        self.assertEqual((sent["status"], sent["format"], sent["output_mime"]), ("sent", "gif", "video/mp4"))


class VideoBudgetTest(unittest.TestCase):
    """The post's files share imaglr's 100 MiB request limit; videos get what the others leave."""

    def member(self, kind="clip", fmt="video", output_bytes=None):
        return {"kind": kind, "format": fmt, "output_bytes": output_bytes, "output_path": None, "output_mime": None}

    def test_single_video_gets_the_whole_request(self):
        self.assertEqual(jobs.video_budget([self.member()]), int(jobs.REQUEST_LIMIT * jobs.SAFETY))

    def test_videos_share_what_images_and_gifs_leave(self):
        members = [self.member("image", "video", 10 * 1048576), self.member(fmt="gif", output_bytes=15 * 1048576),
                   self.member(), self.member()]
        self.assertEqual(jobs.video_budget(members), int((jobs.REQUEST_LIMIT * jobs.SAFETY - 25 * 1048576) / 2))

    def test_no_videos_means_no_sharing(self):
        self.assertEqual(jobs.video_budget([self.member("image", output_bytes=5)]), jobs.VIDEO_LIMIT)

    def test_too_many_files_for_one_post_is_refused_with_advice(self):
        members = [self.member("image", "video", 38 * 1048576)] * 2 + [self.member()] * 10
        with self.assertRaises(jobs.JobFailed) as cm:
            jobs.video_budget(members)
        self.assertIn("Split the post", cm.exception.detail)

    def test_a_file_prepared_for_a_bigger_limit_is_not_reused(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.mp4")
            with open(path, "wb") as f:
                f.write(b"v" * 300)
            m = {"kind": "clip", "format": "video", "output_mime": "video/mp4", "output_path": path, "output_bytes": 300}
            self.assertTrue(jobs._is_prepared(m))
            self.assertTrue(jobs._is_prepared(m, 300))
            self.assertFalse(jobs._is_prepared(m, 299))


class SharedBudgetSendTest(SendHarness):
    """run_send with a post of two video clips: each export is asked to fit half the request."""

    def test_two_videos_in_one_post_each_get_half(self):
        a = items.create_item(self.db, kind="clip", stash_image_id="801", source_title="A", in_s=0.0, out_s=5.0, format="video")
        b = items.create_item(self.db, kind="clip", stash_image_id="802", source_title="B", in_s=0.0, out_s=5.0, format="video",
                              codec="hevc", max_edge=1280)
        post = services.create_post(self.db, [a["id"], b["id"]])
        asked = []

        def fake_export_clip(src, out_dir, **kw):
            from imaglr_integration.media.video_export import ExportResult
            asked.append((kw["settings"].max_video_mb, kw["settings"].codec, kw["settings"].max_long_edge))
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, "c.mp4")
            with open(path, "wb") as f:
                f.write(b"v" * 100)
            return ExportResult(path, 100, 1920, 1080, False, None, "H.265 · 0.0 MB · 1280 px")

        with mock.patch.object(jobs, "export_clip", fake_export_clip), \
             mock.patch.object(jobs, "clip_source", lambda c, m: ("/src.mp4", None)), \
             mock.patch.object(jobs, "hevc_available", lambda ff: True), \
             mock.patch.object(jobs.api, "marker_swap_tags", lambda *a: None, create=True):
            item, client = self.send(post["id"])
        half = int(jobs.REQUEST_LIMIT * jobs.SAFETY / 2) / 1048576
        self.assertEqual(asked, [(half, "h264", 1920), (half, "hevc", 1280)])
        self.assertEqual(items.get_item(self.db, a["id"])["output_note"], "H.265 · 0.0 MB · 1280 px")

    def test_hevc_without_the_encoder_fails_with_advice(self):
        a = items.create_item(self.db, kind="clip", stash_image_id="801", source_title="A", in_s=0.0, out_s=5.0, format="video",
                              codec="hevc")
        with mock.patch.object(jobs, "export_clip", lambda *a_, **k: self.fail("must not encode")), \
             mock.patch.object(jobs, "clip_source", lambda c, m: ("/src.mp4", None)), \
             mock.patch.object(jobs, "hevc_available", lambda ff: False):
            item, _ = self.send(a["id"])
        self.assertEqual((item["status"], item["error_code"]), ("failed", "no_hevc"))
        self.assertIn("Choose H.264", item["error_detail"])


class GifPreviewOpTest(SendHarness):
    """gif_preview makes the clip's GIF now, as the send would, and reports where the editor can show it."""

    def test_preview_prepares_the_gif_and_reports_it(self):
        from imaglr_integration import clip_ops
        from imaglr_integration.media.video_export import ExportResult
        clip = items.create_item(self.db, kind="clip", stash_image_id="801", source_title="Clip", in_s=0.0, out_s=5.0, format="gif")

        def fake_export_gif(src, out_dir, **a):
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, "c.gif")
            with open(path, "wb") as f:
                f.write(b"g" * 100)
            return ExportResult(path, 100, 480, 270, False, None, "GIF · 0.0 MB · 480 px wide · 12 fps")

        ctx = Context({"args": {"mode": "gif_preview", "item_id": clip["id"]}, "server_connection": {"PluginDir": self.tmp.name}})
        ctx._db = self.db
        with mock.patch.object(jobs, "export_gif", fake_export_gif), \
             mock.patch.object(jobs, "clip_source", lambda c, m: ("/src.mp4", None)), \
             mock.patch.object(jobs, "media_tools", lambda c: ("ff", "fp")), \
             mock.patch.object(clip_ops.plugin_settings, "load", lambda s: Settings()):
            out = clip_ops.op_gif_preview(ctx)
        self.assertEqual(out["note"], "GIF · 0.0 MB · 480 px wide · 12 fps")
        self.assertTrue(out["url"].endswith("/c.gif"))
        prepared = items.get_item(self.db, clip["id"])
        self.assertEqual((prepared["output_mime"], prepared["output_bytes"]), ("image/gif", 100))

    def test_preview_needs_a_gif_clip(self):
        from imaglr_integration import clip_ops
        video = items.create_item(self.db, kind="clip", stash_image_id="801", source_title="Clip", in_s=0.0, out_s=5.0, format="video")
        ctx = Context({"args": {"mode": "gif_preview", "item_id": video["id"]}})
        ctx._db = self.db
        with self.assertRaises(UserError):
            clip_ops.op_gif_preview(ctx)

# SPDX-License-Identifier: AGPL-3.0-only
"""Browsing imaglr and saving posts into Stash: the operations and the two save tasks, with Stash and imaglr
stubbed (the real round trip runs in dev/e2e.py); and the guard that keeps saved posts from being uploaded again."""

import json
import os
import tempfile
import unittest
from unittest import mock

from imaglr_integration import blogs, browse_ops, items, jobs, send_ops
from imaglr_integration.cleanup import cleanup_prepared
from imaglr_integration.context import Context, UserError
from imaglr_integration.db import Database
from imaglr_integration.imaglr import ImaglrError, Page
from imaglr_integration.stash import Image, Scene
from imaglr_integration.stash import library

POST = {"id": 7000, "url": "https://imaglr.com/post/7000", "summary": "Golden hour", "created_at": "2026-10-01T12:00:00+00:00",
        "profile": {"name": "sunny", "url": "https://imaglr.com/profile/sunny"}, "tags": ["sunset", "imaglr"],
        "media": [{"url": "https://cdn03.imaglr.com/a.jpg", "kind": "image", "mime": "image/jpeg"}]}
MULTI = dict(POST, id=7002, url="https://imaglr.com/post/7002", media=[{"url": "https://cdn03.imaglr.com/b.jpg", "kind": "image", "mime": "image/jpeg"},
                                   {"url": "https://cdn03.imaglr.com/c.mp4", "kind": "video", "mime": "video/mp4"}])


class FakeStash:
    def __init__(self, settings):
        self.settings = settings
        self.tasks = []

    def gql(self, query, variables=None):
        if "runPluginTask" in query:
            self.tasks.append(variables["args"])
            return {"runPluginTask": str(100 + len(self.tasks))}
        assert "configuration" in query, query
        return {"configuration": {"plugins": {"imaglrIntegration": self.settings}}}


class FakeClient:
    def __init__(self, posts=(POST, MULTI)):
        self.posts = {str(p["id"]): p for p in posts}
        self.calls = []
        self.error = None

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if self.error:
            raise self.error

    def feed(self, nxt=None):
        self._call("feed", nxt)
        return Page(list(self.posts.values()), "https://imaglr.com/api/v2/user/feed?cursor=x")

    def likes(self, nxt=None):
        self._call("likes", nxt)
        return Page([], None)

    def tagged(self, tag, nxt=None):
        self._call("tagged", tag, nxt)
        return Page([], None)

    def profile(self, name):
        self._call("profile", name)
        return {"name": name, "description": "bio", "counts": {"posts": 3}}

    def profile_posts(self, name, nxt=None):
        self._call("profile_posts", name, nxt)
        return Page([], None)

    def post(self, post_id):
        self._call("post", post_id)
        return self.posts[str(post_id)]

    def repost(self, post_id):
        self._call("repost", post_id)
        return {}


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.library = os.path.join(self.tmp.name, "library")
        self.folder = os.path.join(self.library, "imaglr")
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.blog = blogs.add_blog(self.db, "pbk_test_key_123")
        self.stash = FakeStash({"browseImaglr": True, "browseImaglrSaveFolder": self.folder})
        self.client = FakeClient()
        self.refs = {}
        self.credited = []
        patches = [
            mock.patch.object(Context, "imaglr", lambda ctx, blog: self.client),
            mock.patch.object(library, "libraries", lambda s: ([{"path": self.library, "excludeVideo": False, "excludeImage": False}],
                                                               {"scanGenerateCovers": True})),
            mock.patch.object(library, "saved_refs", lambda s, ids: {i: list(self.refs.get(i, [])) for i in ids}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_op(self, mode, **args):
        ctx = Context({"args": {"mode": mode, **args}, "server_connection": {"PluginDir": self.tmp.name}})
        ctx._db = self.db
        ctx._stash = self.stash
        handler = {**browse_ops.OPERATIONS, **browse_ops.TASKS}[mode]
        return handler(ctx)

    def save_row(self, post_id):
        return self.db.fetchone("SELECT * FROM saves WHERE post_id=?", (post_id,))


class BrowseTest(Harness):
    def test_off_until_switched_on(self):
        self.stash.settings = {}
        with self.assertRaises(UserError):
            self.run_op("browse", source="feed")

    def test_a_page_says_what_is_saved_and_what_is_saving(self):
        self.refs = {"7000": [{"kind": "image", "id": "14"}]}
        now = "2026-10-17T10:00:00+00:00"
        self.db.execute("INSERT INTO saves(post_id, status, post, error, created_at, updated_at) VALUES('7002','failed','{}','boom',?,?)", (now, now))
        page = self.run_op("browse", source="feed")
        by_id = {p["id"]: p for p in page["posts"]}
        self.assertEqual(by_id["7000"]["saved"], [{"kind": "image", "id": "14"}])
        self.assertEqual(by_id["7002"]["save"]["error"], "boom")
        self.assertEqual(page["next"], "https://imaglr.com/api/v2/user/feed?cursor=x")
        self.assertEqual(page["blog"]["id"], self.blog["id"])

    def test_a_creator_opens_with_their_profile_once(self):
        first = self.run_op("browse", source="creator", name="@sunny")
        self.assertEqual(first["profile"]["description"], "bio")
        later = self.run_op("browse", source="creator", name="sunny", next="https://imaglr.com/api/v2/profiles/sunny/posts?cursor=2")
        self.assertIsNone(later["profile"])
        self.assertEqual([c[0] for c in self.client.calls].count("profile"), 1)
        self.run_op("browse", source="tag", tag="#sunset")
        self.assertIn(("tagged", "sunset", None), self.client.calls)

    def test_problems_read_well(self):
        with self.assertRaises(UserError):
            self.run_op("browse", source="everything")
        self.client.error = ImaglrError("insufficient_scope")
        with self.assertRaises(UserError) as caught:
            self.run_op("browse", source="feed")
        self.assertIn("isn't allowed to read imaglr", str(caught.exception))
        self.client.error = ImaglrError("post_not_found")
        with self.assertRaises(UserError) as caught:
            self.run_op("post_find", link="https://imaglr.com/post/7000")
        self.assertIn("private or deleted", str(caught.exception))

    def test_find_a_post_by_link(self):
        self.assertEqual(self.run_op("post_find", link="https://imaglr.com/post/7000?ref=x")["post"]["id"], "7000")
        self.assertEqual(self.run_op("post_find", link="7002")["post"]["id"], "7002")
        with self.assertRaises(UserError):
            self.run_op("post_find", link="https://imaglr.com/profile/sunny")


class SaveTest(Harness):
    def test_needs_a_folder_inside_a_library(self):
        self.stash.settings = {"browseImaglr": True}
        with self.assertRaises(UserError):
            self.run_op("save_post", post_id="7000")
        self.stash.settings = {"browseImaglr": True, "browseImaglrSaveFolder": os.path.join(self.tmp.name, "elsewhere")}
        with self.assertRaises(UserError):
            self.run_op("save_post", post_id="7000")
        self.assertEqual(self.stash.tasks, [])

    def test_queues_once_and_not_when_already_saved(self):
        save = self.run_op("save_post", post_id="7000")["save"]
        self.assertEqual(save["status"], "queued")
        self.assertEqual(self.stash.tasks, [{"mode": "task_save", "post_id": "7000"}])
        self.assertEqual(self.run_op("save_post", post_id="7000")["save"]["status"], "queued")
        self.assertEqual(len(self.stash.tasks), 1)  # not twice
        self.refs = {"7002": [{"kind": "gallery", "id": "3"}]}
        self.assertEqual(self.run_op("save_post", post_id="7002")["save"]["status"], "done")
        self.assertEqual(len(self.stash.tasks), 1)

    def test_a_reblog_is_saved_as_the_original(self):
        self.client.posts["111"] = dict(POST, id=111, url="https://imaglr.com/post/111", tags=["reblog"],
                                        profile={"name": "reblogger"}, reposted_from={"id": 7000, "profile": {"name": "sunny"}})
        save = self.run_op("save_post", post_id="111")["save"]
        self.assertEqual(save["post_id"], "7000")
        stored = json.loads(self.save_row("7000")["post"])
        self.assertEqual((stored["id"], stored["tags"]), ("7000", ["sunset", "imaglr"]))  # the original's own
        self.client.posts["112"] = dict(self.client.posts["111"], id=112, reposted_from={"id": 404, "profile": {"name": "gone"}})
        with mock.patch.object(FakeClient, "post", lambda c, i: c.posts[str(i)] if str(i) in c.posts else (_ for _ in ()).throw(ImaglrError("post_not_found"))):
            save = self.run_op("save_post", post_id="112")["save"]
        self.assertEqual(save["post_id"], "404")  # still credited to the original, from the reblog's copy
        self.assertEqual(json.loads(self.save_row("404")["post"])["tags"], ["reblog"])

    def test_a_post_without_pictures_is_not_saved(self):
        self.client.posts["9"] = dict(POST, id=9, media=[])
        with self.assertRaises(UserError):
            self.run_op("save_post", post_id="9")

    def test_download_then_scan_then_credit(self):
        self.run_op("save_post", post_id="7002")
        fetched = []

        def fake_fetch(url, dest, version, **kw):
            fetched.append((url, dest, kw["max_bytes"]))
            with open(dest, "wb") as f:
                f.write(b"data")
            return 4, None
        scans = []
        with mock.patch.object(browse_ops, "fetch_media", fake_fetch), \
             mock.patch.object(library, "scan", lambda s, paths, opts: scans.append((paths, opts)) or "9"):
            self.run_op("task_save", post_id="7002")
        paths = [os.path.join(self.folder, "sunny", "7002-1.jpg"), os.path.join(self.folder, "sunny", "7002-2.mp4")]
        self.assertEqual([d for _, d, _ in fetched], paths)
        self.assertEqual(scans, [(paths, {"scanGenerateCovers": True})])
        self.assertEqual(self.stash.tasks[-1], {"mode": "task_save_apply", "post_id": "7002"})
        row = self.save_row("7002")
        self.assertEqual((row["status"], json.loads(row["files"])), ("scanning", paths))

        found = {paths[0]: {"kind": "image", "id": "21"}, paths[1]: {"kind": "scene", "id": "8"}}
        credited, galleries, names = [], [], []
        candidates = {"tag": [{"id": "1", "name": "Sunset", "aliases": []}, {"id": "9", "name": "imaglr", "aliases": []}],
                      "performer": [{"id": "2", "name": "x", "aliases": ["sunset"]}], "studio": [{"id": "3", "name": "SUNSET", "aliases": []}]}
        with mock.patch.object(library, "find_by_path", lambda s, p: found.get(p)), \
             mock.patch.object(library, "name_candidates", lambda s, tags: names.append(tags) or candidates), \
             mock.patch.object(library, "apply_credit", lambda s, ref, fields: credited.append((ref, fields))), \
             mock.patch.object(library, "create_gallery", lambda s, fields, image_ids: galleries.append((fields, image_ids)) or "5"):
            self.run_op("task_save_apply", post_id="7002")
        self.assertEqual(names, [["sunset", "imaglr"]])  # the workflow tag "imaglr" is never applied (tag 9)
        image_fields = credited[0][1]
        self.assertEqual(image_fields["custom_fields"], {"partial": {"imaglr_post_id": "7002", "imaglr_creator": "sunny"}})
        self.assertEqual(image_fields["urls"], ["https://imaglr.com/post/7002", "https://imaglr.com/profile/sunny"])
        self.assertEqual((image_fields["tag_ids"], image_fields["performer_ids"], image_fields["studio_id"]), (["1"], ["2"], "3"))
        self.assertEqual(image_fields["date"], "2026-10-01")
        self.assertEqual(galleries[0][1], ["21"])
        self.assertEqual(galleries[0][0]["custom_fields"], {"imaglr_post_id": "7002", "imaglr_creator": "sunny"})
        self.assertIn(({"kind": "scene", "id": "8"}, {"gallery_ids": ["5"]}), credited)
        row = self.save_row("7002")
        self.assertEqual(row["status"], "done")
        self.assertEqual(json.loads(row["refs"])[-1], {"kind": "gallery", "id": "5"})

    def test_a_failed_download_leaves_nothing_behind(self):
        self.run_op("save_post", post_id="7002")
        calls = []

        def flaky(url, dest, version, **kw):
            calls.append(dest)
            if len(calls) == 2:
                raise ImaglrError("server_error")
            with open(dest, "wb") as f:
                f.write(b"data")
            return 4, None
        with mock.patch.object(browse_ops, "fetch_media", flaky):
            self.run_op("task_save", post_id="7002")
        self.assertFalse(os.path.exists(calls[0]))
        row = self.save_row("7002")
        self.assertEqual(row["status"], "failed")
        self.assertIn("isn't answering", row["error"])

    def test_stash_not_adding_the_files_is_explained(self):
        self.run_op("save_post", post_id="7000")
        self.db.execute("UPDATE saves SET status='scanning', files=? WHERE post_id='7000'", (json.dumps(["/x/7000.jpg"]),))
        with mock.patch.object(library, "find_by_path", lambda s, p: None):
            self.run_op("task_save_apply", post_id="7000")
        row = self.save_row("7000")
        self.assertEqual(row["status"], "failed")
        self.assertIn("library that takes pictures and videos", row["error"])

    def test_tasks_only_run_what_was_queued(self):
        self.run_op("task_save", post_id="404")  # nothing to do, no error
        self.run_op("save_post", post_id="7000")
        self.run_op("task_save_apply", post_id="7000")  # still queued: the apply step waits for the scan
        self.assertEqual(self.save_row("7000")["status"], "queued")


class FolderTest(Harness):
    def test_choose_a_folder(self):
        stored = []
        with mock.patch.object(library, "set_plugin_config", lambda s, pid, values: stored.append(values)):
            with self.assertRaises(UserError):
                self.run_op("save_folder_set", folder=os.path.join(self.tmp.name, "outside"))
            self.run_op("save_folder_set", folder=os.path.join(self.library, "mine"))
        self.assertEqual(stored, [{"browseImaglrSaveFolder": os.path.join(self.library, "mine")}])
        with mock.patch.object(library, "libraries", lambda s: ([{"path": self.library, "excludeVideo": True}], {})):
            with self.assertRaises(UserError):
                self.run_op("save_folder_set", folder=self.folder)
        setup = self.run_op("save_setup")
        self.assertEqual((setup["enabled"], setup["folder_ok"], setup["folder_writable"]), (True, True, True))
        self.assertTrue(setup["libraries"][0]["writable"])

    def test_a_folder_stash_cant_write_to_is_refused(self):
        with mock.patch.object(library, "set_plugin_config", lambda s, pid, values: self.fail("stored")), \
             mock.patch.object(browse_ops.saving, "probe_write", lambda folder: "Read-only file system"):
            with self.assertRaises(UserError) as caught:
                self.run_op("save_folder_set", folder=self.folder)
        self.assertIn("can't write to that folder (Read-only file system)", str(caught.exception))
        with mock.patch.object(browse_ops.saving, "writable", lambda folder: False):
            self.assertFalse(self.run_op("save_setup")["folder_writable"])
            with self.assertRaises(UserError) as caught:
                self.run_op("save_post", post_id="7000")
        self.assertIn("can't write to the save folder", str(caught.exception))
        self.assertEqual(self.stash.tasks, [])

    def test_a_write_failure_while_saving_says_what_to_do(self):
        self.run_op("save_post", post_id="7000")

        def read_only(url, dest, version, **kw):
            raise OSError(30, "Read-only file system")
        with mock.patch.object(browse_ops, "fetch_media", read_only):
            self.run_op("task_save", post_id="7000")
        row = self.save_row("7000")
        self.assertEqual(row["status"], "failed")
        self.assertIn("couldn't write to the save folder (Read-only file system). Choose another", row["error"])


class PreviewTest(Harness):
    def test_videos_are_fetched_once_and_only_from_imaglr(self):
        with self.assertRaises(UserError):
            self.run_op("media_preview", url="https://elsewhere.example/a.mp4")
        fetched = []

        def fake_fetch(url, dest, version, **kw):
            fetched.append(url)
            with open(dest, "wb") as f:
                f.write(b"v" * 10)
            return 10, "video/mp4"
        with mock.patch.object(browse_ops, "fetch_media", fake_fetch):
            first = self.run_op("media_preview", url="https://cdn03.imaglr.com/a.mp4")
            again = self.run_op("media_preview", url="https://cdn03.imaglr.com/a.mp4")
        self.assertEqual(first, again)
        self.assertEqual(len(fetched), 1)
        self.assertTrue(first["src"].startswith("plugin/imaglrIntegration/assets/prepared/_browse/"))
        self.assertTrue(first["src"].endswith(".mp4"))

    def test_the_preview_folder_stays_under_its_size(self):
        folder = os.path.join(self.tmp.name, "prev")
        os.makedirs(folder)
        for n in range(5):
            path = os.path.join(folder, f"{n}.mp4")
            with open(path, "wb") as f:
                f.write(b"x" * 100)
            os.utime(path, (1000 + n, 1000 + n))
        with mock.patch.object(browse_ops, "PREVIEW_CACHE_BYTES", 250):
            browse_ops._prune_previews(folder, keep="0.mp4")
        self.assertEqual(sorted(os.listdir(folder)), ["0.mp4", "4.mp4"])  # the newest, and the one just fetched

    def test_the_cleanup_leaves_the_preview_folder_alone(self):
        prepared = os.path.join(self.tmp.name, "prepared")
        os.makedirs(os.path.join(prepared, "_browse"))
        os.utime(os.path.join(prepared, "_browse"), (0, 0))
        cleanup_prepared(self.db, prepared, 14)
        self.assertTrue(os.path.isdir(os.path.join(prepared, "_browse")))


class ReblogTest(Harness):
    def test_reblog(self):
        self.assertTrue(self.run_op("reblog", post_id="7000", blog_id=self.blog["id"])["ok"])
        self.assertIn(("repost", "7000"), self.client.calls)
        self.client.error = ImaglrError("insufficient_scope")
        with self.assertRaises(UserError) as caught:
            self.run_op("reblog", post_id="7000", blog_id=self.blog["id"])
        self.assertIn("isn't allowed to reblog", str(caught.exception))
        with self.assertRaises(UserError):
            self.run_op("reblog", post_id="../x", blog_id=self.blog["id"])


class GuardTest(unittest.TestCase):
    """Files saved from imaglr are never uploaded again: send refuses, Send all skips, the send task fails."""

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.ctx = Context({"args": {}})
        self.ctx._db = self.db
        self.ctx._stash = FakeStash({})
        saved = Image.parse({"id": "1", "title": "", "custom_fields": {"imaglr_post_id": "7000"}})
        plain = Image.parse({"id": "2", "title": "", "custom_fields": {}})
        scene = Scene.parse({"id": "3", "title": "", "custom_fields": {"imaglr_post_id": "7002"}})
        patches = [mock.patch.object(jobs.api, "find_image", lambda s, i: {"1": saved, "2": plain}.get(i)),
                   mock.patch.object(jobs.api, "find_scene", lambda s, i: scene if i == "3" else None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_the_custom_field_is_read(self):
        self.assertEqual(Image.parse({"id": "1", "title": "", "custom_fields": {"imaglr_post_id": 5}}).imaglr_post_id, "5")
        self.assertIsNone(Image.parse({"id": "1", "title": ""}).imaglr_post_id)

    def test_saved_files_are_found_through_stills_and_whole_scenes(self):
        saved = items.create_item(self.db, kind="image", stash_image_id="1")
        plain = items.create_item(self.db, kind="image", stash_image_id="2")
        scene = items.create_item(self.db, kind="clip", stash_scene_id="3", in_s=0.0, out_s=4.0)
        still = items.create_item(self.db, kind="still", source_item_id=scene["id"], still_t=1.0)
        self.assertEqual(jobs.saved_from_imaglr(self.ctx, [plain, saved]), "7000")
        self.assertIsNone(jobs.saved_from_imaglr(self.ctx, [plain]))
        self.assertEqual(jobs.saved_from_imaglr(self.ctx, [scene]), "7002")
        self.assertEqual(jobs.saved_from_imaglr(self.ctx, [still]), "7002")

    def test_send_refuses_and_send_all_skips(self):
        saved = items.create_item(self.db, kind="image", stash_image_id="1")
        ctx = Context({"args": {"mode": "send", "item_id": saved["id"]}})
        ctx._db, ctx._stash = self.db, self.ctx._stash
        with self.assertRaises(UserError) as caught:
            send_ops.op_send(ctx)
        self.assertIn("Reblog", str(caught.exception))
        plan = send_ops.plan_send_all(self.ctx, [saved["id"]])
        self.assertEqual(plan[0]["skip"], "from_imaglr")


if __name__ == "__main__":
    unittest.main()


class ReviewTest(Harness):
    """The save review: what each imaglr tag would become, then saving with the choices made."""

    def setUp(self):
        super().setUp()
        self.candidates = {"tag": [{"id": "1", "name": "Sunset", "aliases": []}], "performer": [], "studio": []}
        self.alive = {("tag", "1"): "Sunset", ("tag", "5"): "Golden hour", ("performer", "7"): "Amber", ("tag", "40"): "Made"}
        for p in (mock.patch.object(library, "name_candidates", lambda s, tags: self.candidates),
                  mock.patch.object(library, "existing", lambda s, ts: [{**t, "name": self.alive[(t["kind"], t["id"])]}
                                                                        for t in ts if (t["kind"], t["id"]) in self.alive])):
            p.start()
            self.addCleanup(p.stop)

    def test_rows_say_what_and_why(self):
        from imaglr_integration import import_rules
        import_rules.set_rule(self.db, "golden hour", [{"kind": "tag", "id": "5", "name": "x"}, {"kind": "tag", "id": "99", "name": "gone"}])
        self.client.posts["7000"] = dict(POST, tags=["sunset", "imaglr", "Golden Hour", "beach", "mystery"])
        self.db.execute("INSERT INTO tag_rules(stash_tag, imaglr_tags, created_at, updated_at) VALUES('Seaside', '[\"beach\"]', 'x', 'x')")
        from imaglr_integration.stash import Tag
        with mock.patch.object(browse_ops.api, "find_tag_exact", lambda s, name: Tag("12", "Seaside") if name == "Seaside" else None):
            review = self.run_op("save_review", post_id="7000")
        rows = {r["tag"]: r for r in review["rows"]}
        self.assertNotIn("imaglr", rows)  # the queue tag is never offered
        self.assertEqual((rows["sunset"]["source"], rows["sunset"]["targets"]), ("match", [{"kind": "tag", "id": "1", "name": "Sunset"}]))
        self.assertEqual((rows["Golden Hour"]["source"], rows["Golden Hour"]["targets"]),
                         ("rule", [{"kind": "tag", "id": "5", "name": "Golden hour"}]))  # the deleted target dropped, the name current
        self.assertEqual((rows["beach"]["source"], rows["beach"]["targets"][0]["id"]), ("suggested", "12"))
        self.assertEqual((rows["mystery"]["source"], rows["mystery"]["targets"]), ("none", []))
        self.assertEqual(self.stash.tasks, [])  # nothing saved

    def test_saving_with_choices_creates_remembers_and_applies(self):
        made = []
        from imaglr_integration.stash import Tag
        mapping = [
            {"tag": "sunset", "targets": [{"kind": "tag", "id": "1", "name": "Sunset"}, {"kind": "performer", "id": "7"}], "remember": False},
            {"tag": "imaglr", "targets": [{"kind": "tag", "create": True, "name": "Made"}], "remember": True},
            {"tag": "junk", "targets": [], "remember": True},
            {"tag": "bad", "targets": [{"kind": "scene", "id": "1"}, {"kind": "tag", "id": "1; x"}], "remember": False},
        ]
        with mock.patch.object(browse_ops.api, "ensure_tag", lambda s, name: made.append(name) or Tag("40", name)):
            self.run_op("save_post", post_id="7000", mapping=mapping, extra=[{"kind": "tag", "id": "5"}])
        self.assertEqual(made, ["Made"])
        stored = json.loads(self.save_row("7000")["mapping"])
        self.assertEqual(stored, {"tag_ids": ["1", "40", "5"], "performer_ids": ["7"], "studio_id": None})
        rules = {r["imaglr_tag"]: r["targets"] for r in self.run_op("import_rule_list")["rules"]}
        self.assertEqual(rules, {"imaglr": [{"kind": "tag", "id": "40", "name": "Made"}], "junk": []})
        # the credit step applies exactly what was reviewed
        self.db.execute("UPDATE saves SET status='scanning', files=? WHERE post_id='7000'", (json.dumps(["/x/7000.jpg"]),))
        credited = []
        with mock.patch.object(library, "find_by_path", lambda s, p: {"kind": "image", "id": "3"}), \
             mock.patch.object(library, "apply_credit", lambda s, ref, fields: credited.append(fields)):
            self.run_op("task_save_apply", post_id="7000")
        self.assertEqual((credited[0]["tag_ids"], credited[0]["performer_ids"]), (["1", "40", "5"], ["7"]))
        self.assertNotIn("studio_id", credited[0])
        self.run_op("import_rule_delete", imaglr_tag="JUNK")  # case doesn't matter
        self.assertEqual([r["imaglr_tag"] for r in self.run_op("import_rule_list")["rules"]], ["imaglr"])

    def test_a_save_without_review_uses_rules_and_matches_only(self):
        rows = [{"tag": "a", "targets": [{"kind": "tag", "id": "1", "name": "A"}], "source": "match"},
                {"tag": "b", "targets": [{"kind": "tag", "id": "2", "name": "B"}], "source": "suggested"},
                {"tag": "c", "targets": [{"kind": "studio", "id": "3", "name": "C"}], "source": "match"},
                {"tag": "d", "targets": [{"kind": "studio", "id": "4", "name": "D"}], "source": "rule"}]
        self.assertEqual(browse_ops.automatic_mapping(rows), {"tag_ids": ["1"], "performer_ids": [], "studio_id": None})
        self.assertEqual(browse_ops.automatic_mapping(rows[:3])["studio_id"], "3")

    def test_find_names(self):
        with mock.patch.object(library, "search", lambda s, q: [{"kind": "tag", "id": "1", "name": q}]):
            self.assertEqual(self.run_op("stash_names_find", q="sun")["results"][0]["name"], "sun")


class TopTagsTest(Harness):
    def test_an_empty_search_lists_the_most_used_tags_without_the_workflow_tags(self):
        class Lib:
            def gql(self, query, variables=None):
                return {"scenes": {"tags": [{"id": 1, "name": "Beach"}, {"id": 8, "name": "imaglr"}, {"id": 3, "name": "Dusk"}]},
                        "images": {"tags": [{"id": 1, "name": "Beach"}, {"id": 4, "name": "Portrait"}, {"id": 9, "name": "Imaglr-Sent"}]}}
        self.assertEqual([t["name"] for t in library.top_tags(Lib(), {"imaglr", "imaglr-sent"})], ["Beach", "Portrait", "Dusk"])
        tops = [{"kind": "tag", "id": "5", "name": "AI_Housekeeping"}, {"kind": "tag", "id": "1", "name": "Beach"}]
        with mock.patch.object(library, "top_tags", lambda s, exclude, limit: tops), \
             mock.patch.object(library, "search", lambda s, q: self.fail("searched")):
            self.assertEqual([t["name"] for t in self.run_op("stash_names_find", q="  ")["results"]], ["Beach"])  # "^AI_" by default


class FollowingTest(Harness):
    def test_followed_creators_are_kept_for_an_hour(self):
        self.db.execute("UPDATE blogs SET name='me' WHERE id=?", (self.blog["id"],))
        pages = {None: ([{"name": "a", "avatar": "https://cdn03.imaglr.com/a.jpg"}, {"name": "b"}], "https://imaglr.com/api/v2/profiles/me/following?cursor=2"),
                 "https://imaglr.com/api/v2/profiles/me/following?cursor=2": ([{"name": "b"}, {"name": "c"}], None)}
        calls = []

        def following(name, nxt=None):
            calls.append((name, nxt))
            return pages[nxt]
        self.client.following = following
        people = self.run_op("following")["people"]
        self.assertEqual([p["name"] for p in people], ["a", "b", "c"])
        self.assertEqual(people[0]["avatar"], "https://cdn03.imaglr.com/a.jpg")
        self.assertEqual(self.run_op("following")["people"], people)
        self.assertEqual(len(calls), 2)  # two pages, once: the second call came from the cache
        stale = json.dumps({"at": "2000-01-01T00:00:00+00:00", "people": [{"name": "old", "avatar": None}]})
        self.db.kv_set(f"following:{self.blog['id']}", stale)
        self.client.following = lambda name, nxt=None: (_ for _ in ()).throw(ImaglrError("server_error"))
        self.assertEqual([p["name"] for p in self.run_op("following")["people"]], ["old"])  # imaglr down: stale beats nothing

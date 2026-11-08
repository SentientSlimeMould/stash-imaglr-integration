# SPDX-License-Identifier: AGPL-3.0-only
"""Sync likes and import collections: reading page by page, saving what isn't in the library, stopping where an
earlier likes sync got to, tagging a collection, honouring Stop and imaglr's rate limits; Stash and imaglr stubbed
(the real round trip runs in dev/e2e.py)."""

import json
import os
import unittest
from unittest import mock

from imaglr_integration import browse_ops, likes_sync
from imaglr_integration.context import UserError
from imaglr_integration.imaglr import ImaglrError, Page
from imaglr_integration.stash import library
from tests.python.test_browse_ops import POST, FakeStash, Harness


def post(n, media=True, reblog_of=None):
    p = dict(POST, id=n, url=f"https://imaglr.com/post/{n}", profile={"name": f"c{n % 3}"},
             media=[{"url": f"https://cdn03.imaglr.com/{n}.jpg", "kind": "image", "mime": "image/jpeg"}] if media else [])
    if reblog_of:
        p["reposted_from"] = {"id": reblog_of, "profile": {"name": "orig"}}
    return p


class SyncStash(FakeStash):
    def __init__(self, settings):
        super().__init__(settings)
        self.jobs = []

    def gql(self, query, variables=None):
        if "jobQueue" in query:
            return {"jobQueue": [{"id": j} for j in self.jobs]}
        return super().gql(query, variables)


class SyncHarness(Harness):
    def setUp(self):
        super().setUp()
        self.stash = SyncStash(self.stash.settings)
        self.pages = {}
        self.client.likes = lambda nxt=None, limit=50: self.pages[nxt]
        self.downloads, self.scans = [], []

        def fake_fetch(url, dest, version, **kw):
            self.downloads.append(dest)
            with open(dest, "wb") as f:
                f.write(b"x")
            return 1, None
        for p in (mock.patch.object(likes_sync, "PAUSE", 0), mock.patch.object(likes_sync.time, "sleep", lambda s: None),
                  mock.patch.object(browse_ops, "fetch_media", fake_fetch),
                  mock.patch.object(library, "scan", lambda s, paths, opts: self.scans.append(list(paths)) or "9")):
            p.start()
            self.addCleanup(p.stop)

    def run_op(self, mode, **args):
        from imaglr_integration.context import Context
        ctx = Context({"args": {"mode": mode, **args}, "server_connection": {"PluginDir": self.tmp.name}})
        ctx._db, ctx._stash = self.db, self.stash
        return {**likes_sync.OPERATIONS, **likes_sync.TASKS}[mode](ctx)

    def state(self):
        return json.loads(self.db.kv_get(likes_sync.STATE_KEY) or "{}")


class SyncTest(SyncHarness):
    def test_needs_a_folder_and_starts_a_task(self):
        self.stash.settings = {}
        with self.assertRaises(UserError):
            self.run_op("sync_likes")
        self.stash.settings = {"browseImaglrSaveFolder": self.folder}
        out = self.run_op("sync_likes", everything=True)["sync"]
        self.assertEqual((out["running"], out["everything"], out["phase"]), (True, True, "reading"))
        self.assertEqual(self.stash.tasks[-1], {"mode": "task_sync_likes"})
        self.stash.jobs = [out["job_id"]]
        with self.assertRaises(UserError):
            self.run_op("sync_likes")  # one at a time

    def test_saves_whats_missing_and_credits_it_in_one_go(self):
        self.client.posts.update({"500": post(500)})
        self.pages = {None: Page([post(1), post(2, media=False), post(3), post(4, reblog_of=500)], "next1"),
                      "next1": Page([post(5)], None)}
        self.refs = {"3": [{"kind": "image", "id": "9"}]}  # already saved
        self.run_op("sync_likes")
        self.run_op("task_sync_likes")
        st = self.state()
        self.assertEqual((st["seen"], st["new"], st["known"], st["skipped"], st["failed"]), (5, 3, 1, 1, 0))
        self.assertEqual(st["phase"], "crediting")
        self.assertEqual(len(self.scans), 1)  # one scan for every new file
        self.assertEqual(sorted(os.path.basename(p) for p in self.scans[0]), ["1.jpg", "5.jpg", "500.jpg"])  # the reblog as its original
        apply = self.stash.tasks[-1]
        self.assertEqual(apply["mode"], "task_sync_apply")
        self.assertEqual(sorted(apply["post_ids"].split(",")), ["1", "5", "500"])
        with mock.patch.object(browse_ops, "apply_one", lambda ctx, pid: "done" if pid != "5" else "failed"):
            self.run_op("task_sync_apply", post_ids=apply["post_ids"])
        st = self.state()
        self.assertEqual((st["running"], st["phase"], st["saved"], st["failed"]), (False, "done", 2, 1))

    def test_new_likes_only_stops_where_an_earlier_sync_got_to(self):
        self.pages = {None: Page([post(1), post(2), post(3)], "next1"), "next1": Page([post(4)], None)}
        self.refs = {"2": [{"kind": "image", "id": "1"}], "3": [{"kind": "image", "id": "2"}]}
        with mock.patch.object(likes_sync, "SYNC_KNOWN_RUN", 2):
            self.run_op("sync_likes")
            self.run_op("task_sync_likes")
            self.assertEqual(self.state()["seen"], 3)  # page two never read
            with mock.patch.object(browse_ops, "apply_one", lambda ctx, pid: "done"):
                self.run_op("task_sync_apply", post_ids="1")
            self.run_op("sync_likes", everything=True)
            self.run_op("task_sync_likes")
        self.assertEqual(self.state()["seen"], 4)  # all my likes: on to the end

    def test_stop_and_rate_limits(self):
        calls = []

        def likes(nxt=None, limit=50):
            calls.append(nxt)
            if len(calls) == 1:
                raise ImaglrError("rate_limited", retry_after=5)
            return Page([post(1), post(2)], "more")
        self.client.likes = likes
        self.run_op("sync_likes")

        real = browse_ops.download_files

        def stop_after_first(ctx, p, folder, written, on_file=None):
            likes_sync._set(ctx, stop=True)  # pressed Stop while the first post downloads
            return real(ctx, p, folder, written, on_file)
        with mock.patch.object(browse_ops, "download_files", stop_after_first):
            self.run_op("task_sync_likes")
        st = self.state()
        self.assertEqual(len(calls), 2)  # waited once, then read on
        self.assertEqual((st["seen"], st["new"]), (1, 1))  # stopped after the post it was on
        self.assertEqual(st["phase"], "crediting")  # what was downloaded still gets credited

    def test_a_task_stopped_from_stash_shows_as_stopped(self):
        self.run_op("sync_likes")
        self.stash.jobs = []  # Stash's Tasks page stopped it
        st = self.run_op("sync_status")["sync"]
        self.assertFalse(st["running"])
        self.assertIn("Stopped", st["error"])



def saved(*posts, gone=0):
    """A page of bookmarks: entries for these posts, then `gone` entries whose post was deleted."""
    return [{"post_id": p["id"], "collection_ids": [3], "post": p} for p in posts] + \
        [{"post_id": 90 + n, "collection_ids": [3], "post": None, "unavailable": "deleted"} for n in range(gone)]


class CollectionImportTest(SyncHarness):
    def setUp(self):
        super().setUp()
        self.client.collections = lambda: [{"id": 3, "name": "Beach days", "count": 5}]
        self.collection_pages = {}
        self.client.saved = lambda collection=None, nxt=None, limit=20: (self.collection_pages[(collection, nxt)])
        self.tagged = []
        for p in (mock.patch.object(library, "collection_tag", lambda s, name: f"tag:{name}"),
                  mock.patch.object(library, "add_tag", lambda s, refs, tag: self.tagged.append((tag, sorted(r["id"] for r in refs))))):
            p.start()
            self.addCleanup(p.stop)

    def test_brings_a_collection_up_to_date_and_tags_all_of_it(self):
        self.collection_pages = {("3", None): (saved(post(1), post(2, media=False), post(3), gone=1), "p2"),
                                 ("3", "p2"): (saved(post(4)), None)}
        self.refs = {"3": [{"kind": "image", "id": "30"}]}  # saved before, by hand or a likes sync
        out = self.run_op("import_collection", collection="3")["sync"]
        self.assertEqual((out["source"], out["collection_name"]), ("collection", "Beach days"))
        self.assertEqual(self.stash.tasks[-1], {"mode": "task_sync_likes"})
        with mock.patch.object(likes_sync, "SYNC_KNOWN_RUN", 1):  # no early stop for a collection: every page is read
            self.run_op("task_sync_likes")
        st = self.state()
        self.assertEqual((st["seen"], st["new"], st["known"], st["skipped"], st["gone"]), (4, 2, 1, 1, 1))
        apply = self.stash.tasks[-1]
        self.assertEqual(sorted(apply["post_ids"].split(",")), ["1", "4"])

        def credited(ctx, pid):
            browse_ops._save_update(ctx, pid, status="done", refs=json.dumps([{"kind": "image", "id": f"{pid}0"}]))
            return "done"
        with mock.patch.object(browse_ops, "apply_one", credited):
            self.run_op("task_sync_apply", post_ids=apply["post_ids"])
        self.assertEqual(self.tagged, [("tag:Beach days", ["10", "30", "40"])])  # new and old alike
        self.assertEqual((self.state()["running"], self.state()["saved"]), (False, 2))

    def test_nothing_new_still_tags_what_is_there(self):
        self.collection_pages = {("3", None): (saved(post(3)), None)}
        self.refs = {"3": [{"kind": "scene", "id": "7"}, {"kind": "gallery", "id": "8"}]}
        self.run_op("import_collection", collection="3")
        self.run_op("task_sync_likes")
        self.assertEqual(self.tagged, [("tag:Beach days", ["7", "8"])])
        self.assertEqual((self.state()["running"], self.state()["phase"]), (False, "done"))
        self.assertEqual(len(self.scans), 0)

    def test_all_saved_has_no_tag(self):
        self.collection_pages = {(None, None): (saved(post(3)), None)}
        self.refs = {"3": [{"kind": "image", "id": "30"}]}
        out = self.run_op("import_collection", collection="all")["sync"]
        self.assertEqual(out["collection_name"], "All saved")
        self.run_op("task_sync_likes")
        self.assertEqual(self.tagged, [])

    def test_one_run_at_a_time_and_a_gone_collection(self):
        with self.assertRaises(UserError) as caught:
            self.run_op("import_collection", collection="9")
        self.assertIn("isn't on imaglr any more", str(caught.exception))
        out = self.run_op("import_collection", collection="3")["sync"]
        self.stash.jobs = [out["job_id"]]
        with self.assertRaises(UserError) as caught:
            self.run_op("sync_likes")
        self.assertIn("Beach days", str(caught.exception))

    def test_status_counts_what_can_be_saved(self):
        self.collection_pages = {("3", None): (saved(post(1), post(2, media=False), post(3), post(4, reblog_of=500), gone=1), None)}
        self.refs = {"3": [{"kind": "image", "id": "30"}], "500": [{"kind": "image", "id": "50"}]}  # a reblog is saved as its original
        self.assertEqual(self.run_op("collection_status", collection="3"), {"savable": 3, "in_library": 2})
        with mock.patch.object(likes_sync, "STATUS_PAGES", 1):
            self.collection_pages = {("3", None): (saved(post(1)), "p2")}
            self.assertEqual(self.run_op("collection_status", collection="3"), {"savable": None, "in_library": None})


class CollectionTagTest(unittest.TestCase):
    """library.collection_tag and add_tag against a recording Stash client."""

    class Client:
        def __init__(self, tags):
            self.tags, self.calls = tags, []

        def gql(self, query, variables=None):
            self.calls.append((query, variables))
            if "findTags" in query:
                return {"findTags": {"tags": self.tags}}
            if "tagCreate" in query:
                tag = {"id": str(100 + len(self.tags)), "name": variables["name"], "aliases": []}
                self.tags.append(tag)
                return {"tagCreate": tag}
            return {}

    def test_an_existing_tag_or_alias_is_used_as_it_is(self):
        client = self.Client([{"id": "5", "name": "Seaside", "aliases": ["Beach days"]}])
        self.assertEqual(library.collection_tag(client, "beach days"), "5")
        self.assertFalse(any("tagCreate" in q for q, _ in client.calls))

    def test_a_new_tag_goes_under_imaglr_collections(self):
        client = self.Client([])
        tag = library.collection_tag(client, "Beach days")
        created = [v for q, v in client.calls if "tagCreate" in q]
        self.assertEqual(created[0], {"name": "Imaglr Collections"})
        parent = client.tags[0]["id"]
        self.assertEqual(created[1], {"name": "Beach days", "parent": parent})
        self.assertEqual(tag, client.tags[1]["id"])

    def test_add_tag_adds_a_kind_at_a_time(self):
        client = self.Client([])
        library.add_tag(client, [{"kind": "image", "id": "2"}, {"kind": "scene", "id": "1"}, {"kind": "image", "id": "2"},
                                 {"kind": "gallery", "id": "3"}], "9")
        sent = [(q.split("(input")[0].split()[-1], v) for q, v in client.calls]
        self.assertEqual(sent, [("bulkSceneUpdate", {"ids": ["1"], "t": ["9"]}), ("bulkImageUpdate", {"ids": ["2"], "t": ["9"]}),
                                ("bulkGalleryUpdate", {"ids": ["3"], "t": ["9"]})])
        self.assertTrue(all("mode: ADD" in q for q, _ in client.calls))


if __name__ == "__main__":
    unittest.main()

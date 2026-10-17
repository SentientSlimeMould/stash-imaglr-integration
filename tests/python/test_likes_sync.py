# SPDX-License-Identifier: AGPL-3.0-only
"""Sync likes: reading likes page by page, saving what isn't in the library, stopping where an earlier sync got to,
honouring Stop and imaglr's rate limits; Stash and imaglr stubbed (the real round trip runs in dev/e2e.py)."""

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


class SyncTest(Harness):
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


if __name__ == "__main__":
    unittest.main()

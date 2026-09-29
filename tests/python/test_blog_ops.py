# SPDX-License-Identifier: AGPL-3.0-only
import json
import unittest
from unittest import mock

from imaglr_integration import blog_ops, blogs
from imaglr_integration.context import Context, UserError
from imaglr_integration.db import Database
from imaglr_integration.imaglr import ImaglrError


class FakeClient:
    """Stands in for ImaglrClient; the scenario comes from the key, like dev/fake_imaglr.py."""

    def __init__(self, blog):
        self.name = blog["api_key"].split("|")[0][4:]

    def user_info(self):
        if self.name == "invalid":
            raise ImaglrError("invalid_key", "The key is unknown", http_status=401)
        if self.name == "suspended":
            raise ImaglrError("account_suspended", "Suspended", http_status=403)
        return {"profile": {"name": f"blog-{self.name}", "supporter": self.name != "free", "nsfw": False}}

    def user_limits(self):
        return {"limits": {"posts_per_day": {"limit": 1000, "remaining": 1000}}}


class BlogOpsTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        patcher = mock.patch.object(Context, "imaglr", lambda ctx, blog: FakeClient(blog))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_op(self, name, **args):
        ctx = Context({"args": {"mode": name, **args}})
        ctx._db = self.db
        return blog_ops.OPERATIONS[name](ctx)

    def test_add_checks_the_key_and_labels_the_blog(self):
        blog = self.run_op("blog_add", api_key="pbk_one|secret123")["blog"]
        self.assertEqual((blog["label"], blog["ok"], blog["default_action"]), ("blog-one", True, "draft"))
        self.assertNotIn("secret123", json.dumps(self.run_op("blogs_list")))

    def test_rejected_key_is_not_kept(self):
        with self.assertRaisesRegex(UserError, "didn't accept"):
            self.run_op("blog_add", api_key="pbk_invalid|secret123")
        self.assertEqual(blogs.list_blogs(self.db), [])

    def test_second_key_for_the_same_blog_is_refused(self):
        self.run_op("blog_add", api_key="pbk_one|first-key")
        with self.assertRaisesRegex(UserError, "already added"):
            self.run_op("blog_add", api_key="pbk_one|second-key")
        self.assertEqual(len(blogs.list_blogs(self.db)), 1)

    def test_suspended_account_is_kept_but_paused(self):
        blog = self.run_op("blog_add", api_key="pbk_suspended|secret123")["blog"]
        self.assertEqual((blog["ok"], blog["paused_reason"]), (False, "account_suspended"))

    def test_check_includes_limits_and_non_supporters(self):
        self.run_op("blog_add", api_key="pbk_free|secret123")
        [blog] = self.run_op("blogs_check")["blogs"]
        self.assertIs(blog["supporter"], False)
        self.assertEqual(blog["limits"]["posts_per_day"]["limit"], 1000)

    def test_default_action_and_removal(self):
        blog = self.run_op("blog_add", api_key="pbk_one|secret123", default_action="queue")["blog"]
        self.assertEqual(blog["default_action"], "queue")
        [view] = self.run_op("blog_set_action", blog_id=blog["id"], action="publish")["blogs"]
        self.assertEqual(view["default_action"], "publish")
        with self.assertRaises(UserError):
            self.run_op("blog_set_action", blog_id=blog["id"], action="schedule")
        self.assertEqual(self.run_op("blog_remove", blog_id=blog["id"]), {"blogs": []})


if __name__ == "__main__":
    unittest.main()

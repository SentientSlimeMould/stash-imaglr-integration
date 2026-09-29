# SPDX-License-Identifier: AGPL-3.0-only
import os
import sqlite3
import tempfile
import unittest

from imaglr_integration import blogs, items
from imaglr_integration.db import MIGRATIONS, Database


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database.in_data_dir(os.path.join(self.tmp.name, "data"))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_creates_data_dir_and_migrates(self):
        self.assertEqual(self.db.fetchone("PRAGMA user_version")["user_version"], len(MIGRATIONS))
        self.assertEqual(self.db.fetchone("PRAGMA journal_mode")["journal_mode"], "wal")

    def test_reopening_is_idempotent(self):
        items.create_item(self.db, kind="image", stash_image_id="1")
        self.db.close()
        self.db = Database(self.db.path)
        self.assertEqual(len(items.list_items(self.db)), 1)

    def test_second_connection_sees_writes(self):
        """Operations and tasks run as separate processes against the same file."""
        other = Database(self.db.path)
        try:
            self.db.kv_set("k", "v")
            self.assertEqual(other.kv_get("k"), "v")
        finally:
            other.close()

    def test_transaction_rolls_back(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction() as conn:
                conn.execute("INSERT INTO kv(key, value) VALUES('a', 'b')")
                raise RuntimeError
        self.assertIsNone(self.db.kv_get("a"))


class ItemsTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)

    def test_create_decodes_json_and_bools(self):
        item = items.create_item(self.db, kind="clip", stash_marker_id="7", tags=["a", "b"], mute=True)
        self.assertEqual(item["tags"], ["a", "b"])
        self.assertEqual(item["crop"], items.DEFAULT_CROP)
        self.assertIs(item["mute"], True)
        self.assertEqual(item["status"], "pending")

    def test_status_is_checked(self):
        with self.assertRaises(sqlite3.IntegrityError):
            items.create_item(self.db, kind="image", status="drafted")

    def test_active_for_image_ignores_sent_items(self):
        sent = items.create_item(self.db, kind="image", stash_image_id="5", status="sent")
        self.assertIsNone(items.active_for_image(self.db, "5"))
        items.update_item(self.db, sent["id"], status="failed")
        self.assertEqual(items.active_for_image(self.db, "5")["id"], sent["id"])

    def test_set_members_keep_order_and_cascade(self):
        a, b, c = (items.create_item(self.db, kind="image", stash_image_id=str(n)) for n in range(3))
        group = items.create_item(self.db, kind="set")
        items.set_member_ids(self.db, group["id"], [c["id"], a["id"], b["id"]])
        self.assertEqual([m["id"] for m in items.set_members(self.db, group["id"])], [c["id"], a["id"], b["id"]])
        self.assertEqual(items.set_of(self.db, a["id"]), group["id"])
        items.delete_item(self.db, group["id"])
        self.assertEqual(items.members_index(self.db), {})

    def test_an_item_belongs_to_at_most_one_set(self):
        a = items.create_item(self.db, kind="image")
        one, two = items.create_item(self.db, kind="set"), items.create_item(self.db, kind="set")
        items.set_member_ids(self.db, one["id"], [a["id"]])
        with self.assertRaises(sqlite3.IntegrityError):
            items.set_member_ids(self.db, two["id"], [a["id"]])

    def test_used_tags_count_case_insensitively(self):
        items.bump_used_tags(self.db, ["Sunset", "beach"])
        items.bump_used_tags(self.db, ["sunset"])
        rows = {r["tag"].lower(): r["use_count"] for r in self.db.fetchall("SELECT * FROM used_tags")}
        self.assertEqual(rows, {"sunset": 2, "beach": 1})


class BlogsTest(unittest.TestCase):
    KEY = "pbk_1234|secretvalue9876"

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)

    def test_public_view_never_contains_the_key(self):
        blog = blogs.add_blog(self.db, self.KEY)
        view = blogs.public(blog)
        self.assertNotIn(self.KEY, repr(view))
        self.assertNotIn("secretvalue", repr(view))
        self.assertEqual(view["key_hint"], "pbk_…9876")
        self.assertEqual(view["default_action"], "draft")

    def test_rejects_bad_and_duplicate_keys(self):
        for bad in ("", "abc", "pbk_", "pbk_12 34567890"):
            with self.assertRaises(blogs.BlogError):
                blogs.add_blog(self.db, bad)
        blogs.add_blog(self.db, self.KEY)
        with self.assertRaises(blogs.BlogError):
            blogs.add_blog(self.db, "  " + self.KEY + "\n")

    def test_check_results_label_the_blog(self):
        blog = blogs.add_blog(self.db, self.KEY)
        self.assertIn("not checked", blogs.public(blog)["label"])
        blogs.record_check(self.db, blog["id"], {"name": "myblog", "supporter": True, "nsfw": False}, None)
        view = blogs.public(blogs.get_blog(self.db, blog["id"]))
        self.assertEqual((view["label"], view["ok"], view["supporter"], view["nsfw"]), ("myblog", True, True, False))
        blogs.record_check(self.db, blog["id"], None, ("invalid_key", "The key is unknown"))
        view = blogs.public(blogs.get_blog(self.db, blog["id"]))
        self.assertEqual((view["ok"], view["error_code"], view["label"]), (False, "invalid_key", "myblog"))

    def test_action_resolution(self):
        blog = blogs.add_blog(self.db, self.KEY, default_action="queue")
        self.assertEqual(blogs.resolve_action(blog, None), "queue")
        self.assertEqual(blogs.resolve_action(blog, "publish"), "publish")
        with self.assertRaises(blogs.BlogError):
            blogs.set_default_action(self.db, blog["id"], "schedule")

    def test_removing_a_blog_clears_it_from_items(self):
        blog = blogs.add_blog(self.db, self.KEY)
        item = items.create_item(self.db, kind="image", blog_id=blog["id"])
        blogs.remove_blog(self.db, blog["id"])
        self.assertIsNone(items.get_item(self.db, item["id"])["blog_id"])


if __name__ == "__main__":
    unittest.main()


class TagRuleMigrationTest(unittest.TestCase):
    def test_old_one_to_one_rules_become_lists(self):
        import json

        from imaglr_integration import db as dbmod

        path = os.path.join(tempfile.mkdtemp(), "old.sqlite")
        conn = sqlite3.connect(path, isolation_level=None)
        for n, script in enumerate(dbmod.MIGRATIONS[:2], 1):
            conn.executescript(f"BEGIN;{script}PRAGMA user_version = {n}; COMMIT;")
        conn.executemany(
            "INSERT INTO tag_map(stash_tag, imaglr_tag, created_at, updated_at) VALUES(?, ?, 't', 't')",
            [("Sunset", "golden hour"), ("AI_Junk", None), ('Say "hi"', 'say "hi" \\ back')],
        )
        conn.close()
        with Database(path) as db:
            self.assertEqual(items.tag_mapping(db), {
                "sunset": ["golden hour"], "ai_junk": [], 'say "hi"': ['say "hi" \\ back'],
            })
            self.assertIsNone(db.fetchone("SELECT name FROM sqlite_master WHERE name='tag_map'"))
            json.loads(db.fetchone("SELECT imaglr_tags FROM tag_rules WHERE stash_tag='Sunset'")["imaglr_tags"])

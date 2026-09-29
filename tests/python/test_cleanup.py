# SPDX-License-Identifier: AGPL-3.0-only
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from imaglr_integration import items
from imaglr_integration.cleanup import cleanup_prepared
from imaglr_integration.db import Database

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=20)).isoformat(timespec="seconds")
RECENT = (NOW - timedelta(days=2)).isoformat(timespec="seconds")


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "prepared")
        os.makedirs(self.root)
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)

    def item(self, **fields):
        item = items.create_item(self.db, **fields)
        folder = os.path.join(self.root, item["id"])
        os.makedirs(folder)
        with open(os.path.join(folder, "out.jpg"), "w") as f:
            f.write("x")
        items.update_item(self.db, item["id"], output_path=os.path.join(folder, "out.jpg"))
        self.db.execute("UPDATE items SET updated_at=? WHERE id=?", (fields.get("sent_at") or OLD, item["id"]))
        return item["id"]

    def exists(self, item_id):
        return os.path.isdir(os.path.join(self.root, item_id))

    def test_old_sent_items_lose_their_files(self):
        old = self.item(kind="image", status="sent", sent_at=OLD)
        recent = self.item(kind="image", status="sent", sent_at=RECENT)
        cleanup_prepared(self.db, self.root, 14, NOW)
        self.assertFalse(self.exists(old))
        self.assertTrue(self.exists(recent))
        self.assertIsNone(items.get_item(self.db, old)["output_path"])

    def test_waiting_items_and_failed_stills_are_kept(self):
        ready = self.item(kind="image", status="ready")
        still = self.item(kind="still", status="failed")
        failed = self.item(kind="clip", status="failed")
        cleanup_prepared(self.db, self.root, 14, NOW)
        self.assertTrue(self.exists(ready))
        self.assertTrue(self.exists(still))
        self.assertFalse(self.exists(failed))

    def test_folders_of_deleted_items_go_after_an_hour(self):
        fresh = os.path.join(self.root, "fresh-orphan")
        stale = os.path.join(self.root, "stale-orphan")
        os.makedirs(fresh)
        os.makedirs(stale)
        hour_ago = time.time() - 7200
        os.utime(stale, (hour_ago, hour_ago))
        cleanup_prepared(self.db, self.root, 14, NOW)
        self.assertTrue(os.path.isdir(fresh))
        self.assertFalse(os.path.isdir(stale))

    def test_missing_prepared_folder_is_fine(self):
        self.assertEqual(cleanup_prepared(self.db, os.path.join(self.tmp.name, "nope"), 14, NOW), 0)


if __name__ == "__main__":
    unittest.main()

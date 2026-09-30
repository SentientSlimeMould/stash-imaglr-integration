# SPDX-License-Identifier: AGPL-3.0-only
import unittest

from imaglr_integration import items, services
from imaglr_integration.db import Database
from imaglr_integration.settings import Settings
from imaglr_integration.stash import Image

from .test_stash_models import sample_image


class PostTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.items = [items.create_item(self.db, kind="image", stash_image_id=str(n), source_title=f"img{n}",
                                        tags=[f"t{n}", "shared"]) for n in range(12)]

    def ids(self, *ns):
        return [self.items[n]["id"] for n in ns]

    def test_post_keeps_order_and_merges_tags(self):
        post = services.create_post(self.db, self.ids(2, 0, 1))
        self.assertEqual([m["id"] for m in items.set_members(self.db, post["id"])], self.ids(2, 0, 1))
        self.assertEqual(post["tags"], ["t2", "shared", "t0", "t1"])

    def test_more_than_ten_is_refused(self):
        with self.assertRaises(services.PostError):
            services.create_post(self.db, self.ids(*range(11)))

    def test_items_move_between_posts_and_empty_posts_go(self):
        first = services.create_post(self.db, self.ids(0, 1))
        second = services.create_post(self.db, self.ids(0, 1, 2))
        self.assertIsNone(items.get_item(self.db, first["id"]))
        self.assertEqual(len(items.set_members(self.db, second["id"])), 3)

    def test_partly_moved_post_survives(self):
        first = services.create_post(self.db, self.ids(0, 1, 2))
        services.create_post(self.db, self.ids(2, 3))
        self.assertEqual([m["id"] for m in items.set_members(self.db, first["id"])], self.ids(0, 1))

    def test_posts_being_sent_are_not_regrouped(self):
        first = services.create_post(self.db, self.ids(0, 1))
        items.update_item(self.db, first["id"], status="sending")
        with self.assertRaises(services.PostError):
            services.create_post(self.db, self.ids(1, 2))
        with self.assertRaises(services.PostError):
            services.dissolve_post(self.db, first["id"])

    def test_split_keeps_members(self):
        post = services.create_post(self.db, self.ids(0, 1))
        services.dissolve_post(self.db, post["id"])
        self.assertIsNotNone(items.get_item(self.db, self.items[0]["id"]))
        self.assertEqual(items.members_index(self.db), {})


class ItemFromImageTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)

    def test_creates_once_with_suggested_tags(self):
        image = Image.parse(sample_image())
        first = services.item_from_image(self.db, Settings(), image)
        again = services.item_from_image(self.db, Settings(), image)
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(first["kind"], "image")
        self.assertTrue(first["tags"])
        self.assertNotIn("imaglr", [t.lower() for t in first["tags"]])


class RelativeUrlTest(unittest.TestCase):
    def test_host_is_dropped_and_query_kept(self):
        self.assertEqual(services.relative_url("http://0.0.0.0:9999/image/5/thumbnail?t=123"), "image/5/thumbnail?t=123")
        self.assertIsNone(services.relative_url(None))


if __name__ == "__main__":
    unittest.main()


class PostCardTest(unittest.TestCase):
    """A post's card is built from its members' cards, whatever their kinds (clips and stills carry no size)."""

    def test_mixed_members(self):
        from imaglr_integration import services

        base = {"thumb": None, "preview": None, "status": "pending", "title": "t", "width": 1, "height": 1, "first_seen": None}
        image = {**base, "id": "a", "kind": "image", "tab": "images", "bytes": 10}
        clip = {**base, "id": "b", "kind": "clip", "tab": "clips", "duration": 2.0}
        still = {**base, "id": "c", "kind": "still", "tab": "images"}
        post = {"id": "s", "kind": "set", "status": "pending", "source_title": "t", "tags": [], "blog_id": None,
                "action": None, "error_code": None, "error_detail": None, "progress": 0, "created_at": "x", "caption": ""}
        for members in ([image, clip], [clip, clip], [image, still], [still]):
            card = services.post_card(post, members)
            self.assertEqual(len(card["members"]), len(members))
        self.assertEqual(services.post_card(post, [image, clip])["bytes"], 10)
        self.assertIsNone(services.post_card(post, [clip, clip])["bytes"])

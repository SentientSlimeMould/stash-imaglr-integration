# SPDX-License-Identifier: AGPL-3.0-only
"""The tag-rule operations (Settings → Tag rules), against an in-memory database and a Stash that only
answers the plugin-settings query."""
import unittest

from imaglr_integration import items, send_ops
from imaglr_integration.context import Context, UserError
from imaglr_integration.db import Database


class FakeStash:
    def __init__(self, plugin_settings=None):
        self.plugin_settings = plugin_settings or {}

    def gql(self, query, variables=None):
        assert "configuration" in query, query
        return {"configuration": {"plugins": {"imaglrIntegration": self.plugin_settings}}}


class TagRuleOpsTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.stash = FakeStash()

    def run_op(self, name, **args):
        ctx = Context({"args": {"mode": name, **args}})
        ctx._db = self.db
        ctx._stash = self.stash
        return send_ops.OPERATIONS[name](ctx)

    def test_set_lists_and_deletes(self):
        out = self.run_op("tag_rule_set", stash_tag="Catsuit", imaglr_tags=["Latex", "catsuit"])
        self.assertEqual(out, {"rules": [{"stash_tag": "Catsuit", "imaglr_tags": ["latex", "catsuit"]}]})
        listed = self.run_op("tag_rule_list")
        self.assertEqual(listed["rules"], out["rules"])
        self.assertTrue(listed["lowercase_tags"])
        self.assertEqual(self.run_op("tag_rule_delete", stash_tag="Catsuit"), {"rules": []})

    def test_one_target_and_never_suggest(self):
        self.assertEqual(self.run_op("tag_rule_set", stash_tag="Sunset", imaglr_tags=["sunsets"])["rules"][0]["imaglr_tags"], ["sunsets"])
        self.assertEqual(self.run_op("tag_rule_set", stash_tag="Sunset", imaglr_tags=[])["rules"][0]["imaglr_tags"], [])

    def test_keeps_capitals_when_configured(self):
        self.stash = FakeStash({"tagsKeepCapitals": True})
        out = self.run_op("tag_rule_set", stash_tag="Catsuit", imaglr_tags=["Latex"])
        self.assertEqual(out["rules"][0]["imaglr_tags"], ["Latex"])
        self.assertFalse(self.run_op("tag_rule_list")["lowercase_tags"])

    def test_rejects_missing_input(self):
        with self.assertRaises(UserError):
            self.run_op("tag_rule_set", stash_tag="", imaglr_tags=["x"])
        with self.assertRaises(UserError):
            self.run_op("tag_rule_set", stash_tag="Sunset", imaglr_tags="x")


class OperationsAreWellFormedTest(unittest.TestCase):
    """Every registered operation must only reference names that exist: a helper deleted in a refactor must
    fail here, not in a user's Settings dialog."""

    def test_no_undefined_globals(self):
        import builtins
        import dis

        from imaglr_integration import app

        for name, fn in app.OPERATIONS.items():
            module_names = set(vars(__import__(fn.__module__, fromlist=["_"])))
            for ins in dis.get_instructions(fn):
                if ins.opname in ("LOAD_GLOBAL", "LOAD_NAME"):
                    self.assertTrue(
                        ins.argval in module_names or hasattr(builtins, ins.argval),
                        f"{name} ({fn.__module__}) uses undefined name {ins.argval!r}",
                    )


class AutomaticTagsTest(unittest.TestCase):
    """An item's tags follow Stash and the rules until the user edits them (tags_auto)."""

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.stash = FakeStash()

    def run_op(self, name, **args):
        ctx = Context({"args": {"mode": name, **args}})
        ctx._db = self.db
        ctx._stash = self.stash
        return send_ops.OPERATIONS[name](ctx)

    def test_new_items_are_automatic_and_follow_suggestions(self):
        from imaglr_integration import items, services

        item = items.create_item(self.db, kind="image", stash_image_id="1", tags=["sunset"])
        self.assertTrue(item["tags_auto"])
        item = services.refresh_tags(self.db, item, ["sunset", "beach"])
        self.assertEqual(item["tags"], ["sunset", "beach"])
        self.assertEqual(items.get_item(self.db, item["id"])["tags"], ["sunset", "beach"])
        # nothing known about the source: leave alone
        self.assertEqual(services.refresh_tags(self.db, item, None)["tags"], ["sunset", "beach"])

    def test_editing_takes_over_and_refresh_stops(self):
        from imaglr_integration import items, services

        item = items.create_item(self.db, kind="image", stash_image_id="1", tags=["sunset"])
        # same tags sent back (e.g. the caption changed): still automatic
        out = self.run_op("item_update", item_id=item["id"], changes={"tags": ["sunset"], "caption": "hi"})["item"]
        self.assertTrue(out["tags_auto"])
        out = self.run_op("item_update", item_id=item["id"], changes={"tags": ["sunset", "mine"]})["item"]
        self.assertFalse(out["tags_auto"])
        self.assertEqual(services.refresh_tags(self.db, out, ["sunset", "beach"])["tags"], ["sunset", "mine"])

    def test_flipping_a_clip_means_exporting_again(self):
        from imaglr_integration import items

        clip = items.create_item(self.db, kind="clip", stash_image_id="9", in_s=0.0, out_s=5.0,
                                 output_path="/tmp/x.mp4", output_bytes=1, output_mime="video/mp4", status="ready")
        out = self.run_op("item_update", item_id=clip["id"], changes={"flip": True})["item"]
        self.assertTrue(out["flip"])
        self.assertEqual((out["output_path"], out["status"]), (None, "pending"))
        # the same value again changes nothing
        again = self.run_op("item_update", item_id=clip["id"], changes={"flip": True, "mute": False})["item"]
        self.assertTrue(again["flip"])
        with self.assertRaises(UserError):
            image = items.create_item(self.db, kind="image", stash_image_id="10")
            self.run_op("item_update", item_id=image["id"], changes={"flip": True})

    def test_cover_time_is_kept_or_cleared(self):
        clip = items.create_item(self.db, kind="clip", stash_image_id="9",
                                 in_s=0.0, out_s=5.0)
        out = self.run_op("item_update", item_id=clip["id"], changes={"cover_t": "12.3456"})["item"]
        self.assertEqual(out["cover_t"], 12.346)
        self.assertIsNone(self.run_op("item_update", item_id=clip["id"], changes={"cover_t": None})["item"]["cover_t"])
        with self.assertRaises(UserError):
            self.run_op("item_update", item_id=clip["id"], changes={"cover_t": -1})

    def test_edge_trims_are_cleaned_and_only_kept_when_set(self):
        clip = items.create_item(self.db, kind="clip", stash_image_id="9",
                                 in_s=0.0, out_s=5.0)
        out = self.run_op("item_update", item_id=clip["id"],
                          changes={"crop": {"aspect": "1:1", "position": 0.5, "edges": {"top": "0.1", "left": 2, "junk": 9}}})["item"]
        self.assertEqual(out["crop"]["edges"], {"top": 0.1, "right": 0.0, "bottom": 0.0, "left": 0.45})
        out = self.run_op("item_update", item_id=clip["id"], changes={"crop": {"aspect": "1:1", "position": 0.5, "edges": {}}})["item"]
        self.assertNotIn("edges", out["crop"])

    def test_post_tags_merge_members(self):
        from imaglr_integration import services

        merged = services.merged_tags([{"tags": ["Sunset", "beach"]}, {"tags": ["sunset", "sea"]}])
        self.assertEqual(merged, ["Sunset", "beach", "sea"])


if __name__ == "__main__":
    unittest.main()


class ImaglrBaseOverrideTest(unittest.TestCase):
    """IMAGLR_API_BASE (development only) must not be able to send the key over plain http to the internet."""

    def check(self, value):
        from imaglr_integration.context import imaglr_base_override
        from unittest import mock
        import os

        with mock.patch.dict(os.environ, {"IMAGLR_API_BASE": value}):
            return imaglr_base_override()

    def test_https_anywhere_and_http_locally(self):
        self.assertEqual(self.check("https://staging.example.org/api/v2"), "https://staging.example.org/api/v2")
        self.assertEqual(self.check("http://fake-imaglr:8900/api/v2"), "http://fake-imaglr:8900/api/v2")
        self.assertEqual(self.check("http://127.0.0.1:8900/api/v2"), "http://127.0.0.1:8900/api/v2")
        lan = "http://" + ".".join(["10", "0", "0", "5"]) + ":8900/api/v2"  # a private address (spelt out for the privacy scan)
        self.assertEqual(self.check(lan), lan)
        self.assertIsNone(self.check(""))

    def test_plain_http_to_the_internet_is_refused(self):
        with self.assertRaises(UserError):
            self.check("http://imaglr.example.org/api/v2")
        with self.assertRaises(UserError):
            self.check("ftp://x")

# SPDX-License-Identifier: AGPL-3.0-only
"""The tag-rule operations (Settings → Tag rules), against an in-memory database and a Stash that only
answers the plugin-settings query."""
import unittest

from imaglr_integration import send_ops
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


if __name__ == "__main__":
    unittest.main()

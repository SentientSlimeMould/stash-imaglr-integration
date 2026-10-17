# SPDX-License-Identifier: AGPL-3.0-only
"""Import rules and the tag plan for a saved post (pure, with an in-memory database)."""

import unittest

from imaglr_integration import import_rules as ir
from imaglr_integration.db import Database


class PlanTest(unittest.TestCase):
    def test_rule_then_match_then_suggestion_then_nothing(self):
        candidates = {"tag": [{"id": 1, "name": "Beach", "aliases": ["seaside"]}, {"id": 9, "name": "imaglr", "aliases": []}],
                      "performer": [{"id": 2, "name": "Amber", "aliases": []}, {"id": 3, "name": "Amber Rose", "aliases": []}],
                      "studio": []}
        rows = ir.plan(["Seaside", "amber", "Dusk", "odd", "imaglr", "seaside ", "Mine"],
                       {"mine": [{"kind": "tag", "id": "4", "name": "M"}]}, candidates,
                       {"dusk": [{"kind": "tag", "id": "5", "name": "Evening"}]}, {"imaglr", "imaglr-sent"})
        self.assertEqual([(r["tag"], r["source"], [t["id"] for t in r["targets"]]) for r in rows], [
            ("Seaside", "match", ["1"]),       # by alias, whatever the case
            ("amber", "match", ["2"]),         # a whole name only: never Amber Rose
            ("Dusk", "suggested", ["5"]),
            ("odd", "none", []),
            ("Mine", "rule", ["4"]),
        ])  # the workflow tag and the repeat are left out

    def test_a_rule_to_nothing_overrides_a_match(self):
        rows = ir.plan(["beach"], {"beach": []}, {"tag": [{"id": 1, "name": "Beach", "aliases": []}]}, {}, set())
        self.assertEqual((rows[0]["source"], rows[0]["targets"]), ("rule", []))

    def test_resolve_keeps_one_studio_and_no_repeats(self):
        out = ir.resolve([{"kind": "tag", "id": "1"}, {"kind": "tag", "id": "1"}, {"kind": "performer", "id": "2"},
                          {"kind": "studio", "id": "3"}, {"kind": "studio", "id": "4"}, {"kind": "tag", "create": True, "name": "x"}])
        self.assertEqual(out, {"tag_ids": ["1"], "performer_ids": ["2"], "studio_id": "3"})


class TargetsTest(unittest.TestCase):
    def test_only_well_formed_targets(self):
        cleaned = ir.clean_targets([
            {"kind": "tag", "id": "1", "name": " Sun  set "}, {"kind": "tag", "id": 1}, {"kind": "scene", "id": "2"},
            {"kind": "tag", "id": "1); drop"}, {"kind": "performer", "create": True, "name": "x"},
            {"kind": "tag", "create": True, "name": "New"}, {"kind": "tag", "create": True, "name": "new"}, "junk"])
        self.assertEqual(cleaned, [{"kind": "tag", "id": "1", "name": "Sun set"}, {"kind": "tag", "create": True, "name": "New"}])
        self.assertEqual(ir.clean_targets(None), [])


class StoreTest(unittest.TestCase):
    def test_rules_round_trip_ignoring_case(self):
        db = Database(":memory:")
        self.addCleanup(db.close)
        ir.set_rule(db, "Golden  Hour", [{"kind": "tag", "id": "5", "name": "G"}, {"kind": "tag", "create": True, "name": "N"}])
        ir.set_rule(db, "junk", [])
        ir.set_rule(db, "golden hour", [{"kind": "performer", "id": "7", "name": "P"}])  # replaces, whatever the case
        ir.set_rule(db, "   ", [{"kind": "tag", "id": "1"}])  # no tag: nothing stored
        self.assertEqual(ir.list_rules(db), [{"imaglr_tag": "Golden Hour", "targets": [{"kind": "performer", "id": "7", "name": "P"}]},
                                             {"imaglr_tag": "junk", "targets": []}])
        self.assertEqual(ir.rules_for(db, ["GOLDEN HOUR", "other"]), {"golden hour": [{"kind": "performer", "id": "7", "name": "P"}]})
        ir.delete_rule(db, "Junk")
        self.assertEqual([r["imaglr_tag"] for r in ir.list_rules(db)], ["Golden Hour"])


if __name__ == "__main__":
    unittest.main()

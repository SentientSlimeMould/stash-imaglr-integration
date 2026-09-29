# SPDX-License-Identifier: AGPL-3.0-only
import re
import unittest

from imaglr_integration.stash.models import Image, Marker
from imaglr_integration.tags.pipeline import (
    RawTag,
    SuggestedTag,
    Suggestions,
    TagConfig,
    collect_clip_sources,
    collect_image_sources,
    dropped_tags,
    merge_suggestions,
    parse_patterns,
    suggest,
    validate_tags,
)

from .test_stash_models import sample_image, sample_marker

CFG = TagConfig("imaglr", "imaglr-drafted", (re.compile("^AI_", re.I),), True)


class SuggestTest(unittest.TestCase):
    def test_clip_source_order_and_workflow_removal(self):
        m = Marker.parse(sample_marker())
        raw = collect_clip_sources(m, m.scene)
        self.assertEqual([r.name for r in raw][:3], ["imaglr", "Slow Motion", "AI_face"])
        s = suggest(raw, CFG, {})
        # case-insensitive dedupe keeps the first
        self.assertEqual(s.active_names(), ["slow motion", "outdoor", "alex doe", "studio x"])
        self.assertEqual((s.active[0].source, s.active[2].source), ("marker", "performer"))

    def test_image_source_order(self):
        s = suggest(collect_image_sources(Image.parse(sample_image())), CFG, {})
        self.assertEqual(s.active_names(), ["portrait", "alex doe", "summer"])
        self.assertEqual([t.source for t in s.active], ["image", "performer", "gallery"])

    def test_workflow_tags_match_whatever_their_case(self):
        s = suggest([RawTag("Imaglr", "image"), RawTag("IMAGLR-Drafted", "image"), RawTag("x", "image")], CFG, {})
        self.assertEqual(s.active_names(), ["x"])

    def test_default_exclusion_is_ai_prefix(self):
        cfg = TagConfig("imaglr", "imaglr-drafted")
        s = suggest([RawTag("AI_Housekeeping", "scene"), RawTag("ai_face", "scene"), RawTag("Beach", "scene")], cfg, {})
        self.assertEqual(s.active_names(), ["beach"])

    def test_parse_patterns_skips_invalid(self):
        self.assertEqual([p.pattern for p in parse_patterns(" ^AI_ , [bad, x$ ,")], ["^AI_", "x$"])
        self.assertTrue(parse_patterns("^ai_")[0].search("AI_face"))

    def test_mapping_and_drop(self):
        raw = [RawTag("Slow Motion", "scene"), RawTag("Outdoor", "scene"), RawTag("Studio X", "studio")]
        s = suggest(raw, CFG, {"slow motion": "slowmo", "outdoor": None})
        self.assertEqual(s.active_names(), ["slowmo", "studio x"])
        self.assertEqual(s.active[0].original, "Slow Motion")

    def test_thirty_five_tags_keeps_thirty_and_greys_rest(self):
        s = suggest([RawTag(f"tag{i}", "scene") for i in range(35)], CFG, {})
        self.assertEqual(len(s.active), 30)
        self.assertEqual(len(s.greyed), 5)
        self.assertTrue(all(g.reason == "over_limit" for g in s.greyed))

    def test_seventy_char_tag_is_greyed_with_reason(self):
        long = "x" * 70
        s = suggest([RawTag(long, "scene"), RawTag("ok", "scene")], CFG, {})
        self.assertEqual(s.active_names(), ["ok"])
        self.assertEqual((s.greyed[0].reason, s.greyed[0].tag), ("too_long", long))

    def test_whitespace_and_case_normalisation(self):
        s = suggest([RawTag("  Foo   Bar ", "scene"), RawTag("foo bar", "scene")], CFG, {})
        self.assertEqual(s.active_names(), ["foo bar"])
        s2 = suggest([RawTag("Foo Bar", "scene")], TagConfig("q", "d", (), False), {})
        self.assertEqual(s2.active_names(), ["Foo Bar"])

    def test_to_dict(self):
        s = suggest([RawTag("A", "scene")], CFG, {})
        self.assertEqual(s.to_dict(), {"active": [{"tag": "a", "source": "scene", "original": "A", "reason": None}], "greyed": []})


class ValidateTest(unittest.TestCase):
    def test_validate_tags(self):
        self.assertEqual(validate_tags([" A ", "a", "b"], CFG), ["a", "b"])
        with self.assertRaises(ValueError):
            validate_tags(["x" * 65], CFG)
        with self.assertRaises(ValueError):
            validate_tags([f"t{i}" for i in range(31)], CFG)

    def test_dropped_tags_case_insensitive(self):
        self.assertEqual(dropped_tags(["a", "Banned", "c"], ["A", "c"]), ["Banned"])


def sugg(names, greyed=(), source="image"):
    return Suggestions(
        [SuggestedTag(n, source, n) for n in names], [SuggestedTag(n, source, n, "too_long") for n in greyed]
    )


class MergeTest(unittest.TestCase):
    def test_members_in_order_deduplicated(self):
        merged = merge_suggestions([sugg(["t1", "shared"]), sugg(["Shared", "t2"], source="marker")])
        self.assertEqual(merged.active_names(), ["t1", "shared", "t2"])
        self.assertEqual(merged.active[2].source, "marker")

    def test_greyed_are_kept_once(self):
        long = "x" * 70
        merged = merge_suggestions([sugg(["a"], [long]), sugg(["b"], [long])])
        self.assertEqual(merged.active_names(), ["a", "b"])
        self.assertEqual([g.tag for g in merged.greyed], [long])

    def test_cap_moves_overflow_to_the_front_of_greyed(self):
        long = "x" * 70
        merged = merge_suggestions([sugg([f"a{i}" for i in range(20)], [long]), sugg([f"b{i}" for i in range(20)])])
        self.assertEqual(len(merged.active), 30)
        self.assertEqual(merged.active_names()[-1], "b9")
        self.assertEqual([g.tag for g in merged.greyed[:10]], [f"b{i}" for i in range(10, 20)])
        self.assertTrue(all(g.reason == "over_limit" for g in merged.greyed[:10]))
        self.assertEqual(merged.greyed[-1].tag, long)

    def test_empty(self):
        self.assertEqual(merge_suggestions([]).to_dict(), {"active": [], "greyed": []})


if __name__ == "__main__":
    unittest.main()

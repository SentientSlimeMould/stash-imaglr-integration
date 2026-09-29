// SPDX-License-Identifier: AGPL-3.0-only
import { test } from "node:test";
import assert from "node:assert/strict";
import { activate, activeNames, addTag, chipsFromSuggestions, removeTag, replaceChip } from "../../src/ui/lib/tags.ts";
import type { Suggestions } from "../../src/ui/lib/types.ts";

const sugg: Suggestions = {
  active: [{ tag: "a", source: "marker", original: "A", reason: null }, { tag: "b", source: "scene", original: "b", reason: null }],
  greyed: [
    { tag: "x".repeat(70), source: "scene", original: "x", reason: "too_long" },
    { tag: "spare", source: "scene", original: "spare", reason: "over_limit" },
  ],
};

test("chipsFromSuggestions reflects saved selection and manual additions", () => {
  const chips = chipsFromSuggestions(sugg, ["b", "manual one"]);
  assert.equal(chips.find((c) => c.name === "a")?.state, "parked");
  assert.equal(chips.find((c) => c.name === "b")?.state, "active");
  assert.equal(chips.find((c) => c.name === "manual one")?.source, "manual");
  assert.equal(chips.find((c) => c.reason?.includes("64"))?.state, "too_long");
  assert.deepEqual(activeNames(chips), ["b", "manual one"]);
});

test("addTag normalises and rejects long and duplicate tags", () => {
  const chips = chipsFromSuggestions(sugg, null);
  const r = addTag(chips, "  New   Tag ", true);
  assert.equal(r.ok && r.chips[r.chips.length - 1].name, "new tag");
  assert.equal(addTag(chips, "z".repeat(64), true).ok, true);
  assert.equal(addTag(chips, "z".repeat(65), true).ok, false);
  const dup = addTag(chips, "A", true);
  assert.equal(dup.ok, false);
  assert.equal(!dup.ok && dup.existing, "a");
});

test("addTag re-activates a parked duplicate", () => {
  const chips = chipsFromSuggestions(sugg, null);
  const r = addTag(chips, "SPARE", false);
  assert.ok(r.ok);
  assert.ok(activeNames(r.chips).includes("spare"));
  assert.equal(r.chips.filter((c) => c.name.toLowerCase() === "spare").length, 1);
});

test("addTag parks additions beyond 30 and activate works when there is room", () => {
  const active = Array.from({ length: 30 }, (_, i) => ({ tag: `t${i}`, source: "scene", original: "", reason: null }));
  let chips = chipsFromSuggestions({ active, greyed: [] }, null);
  const r = addTag(chips, "extra", true);
  assert.equal(r.ok && r.parked, true);
  chips = r.ok ? r.chips : chips;
  assert.equal(activate(chips, "extra").ok, false);
  chips = removeTag(chips, "t0");
  const a = activate(chips, "extra");
  assert.ok(a.ok && activeNames(a.chips).includes("extra"));
  assert.equal(activeNames(chips).length, 29);
});

test("removeTag parks suggested chips and drops manual ones", () => {
  const chips = chipsFromSuggestions(sugg, ["a", "mine"]);
  const after = removeTag(removeTag(chips, "a"), "mine");
  assert.equal(after.find((c) => c.name === "a")?.state, "parked");
  assert.equal(after.some((c) => c.name === "mine"), false);
});

test("replaceChip maps and drops", () => {
  const chips = chipsFromSuggestions(sugg, null);
  assert.equal(replaceChip(chips, "a", null).some((c) => c.name === "a"), false);
  const mapped = replaceChip(chips, "a", "alpha");
  assert.equal(mapped.find((c) => c.name === "alpha")?.original, "A");
  assert.equal(replaceChip(chips, "a", "b").filter((c) => c.name === "b").length, 1);
});

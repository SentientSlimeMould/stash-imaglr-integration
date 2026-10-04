// SPDX-License-Identifier: AGPL-3.0-only
import { test } from "node:test";
import assert from "node:assert/strict";
import { addOptionFirst, checkNewTag, normalise, spareSuggestions } from "../../src/ui/lib/tags.ts";

test("normalise trims, collapses spaces and optionally lowercases", () => {
  assert.equal(normalise("  Beach   Day ", true), "beach day");
  assert.equal(normalise("  Beach   Day ", false), "Beach Day");
});

test("typed tags are normalised, limited and de-duplicated", () => {
  assert.deepEqual(checkNewTag(["sunset"], "  Beach   Day ", true), { ok: true, tag: "beach day" });
  assert.equal(checkNewTag(["sunset"], "SUNSET", true).ok, false);
  assert.equal(checkNewTag([], "x".repeat(64), true).ok, true);
  assert.equal(checkNewTag([], "x".repeat(65), true).ok, false);
  assert.equal(checkNewTag(Array.from({ length: 30 }, (_, i) => `t${i}`), "one more", true).ok, false);
  assert.deepEqual(checkNewTag([], "Keep Case", false), { ok: true, tag: "Keep Case" });
});

test("spare suggestions exclude tags already on the post and split out over-long ones", () => {
  const s = {
    active: [{ tag: "sunset", source: "marker", original: "Sunset", reason: null }],
    greyed: [
      { tag: "beach", source: "scene", original: "Beach", reason: "over_limit" as const },
      { tag: "a".repeat(70), source: "scene", original: "Very long tag", reason: "too_long" as const },
    ],
  };
  assert.deepEqual(spareSuggestions(s, ["Sunset"]), { addable: ["beach"], tooLong: ["Very long tag"] });
});

test("what you typed is offered first unless a suggestion starts with it", () => {
  assert.equal(addOptionFirst("humping", ["dry humping"]), true); // contains it, but you typed something else
  assert.equal(addOptionFirst("vint", ["vintage", "retro"]), false); // completing "vintage"
  assert.equal(addOptionFirst("Vint", ["vintage"]), false);
  assert.equal(addOptionFirst("new", []), true);
});

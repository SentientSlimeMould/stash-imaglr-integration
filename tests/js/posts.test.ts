// SPDX-License-Identifier: AGPL-3.0-only
import assert from "node:assert/strict";
import { test } from "node:test";
import { mediaRatio, parseSearch, relativeTime, savedPath, shortCount } from "../../src/ui/lib/posts.ts";

test("how long ago, then the date", () => {
  const now = new Date("2026-10-17T12:00:00Z");
  assert.equal(relativeTime("2026-10-17T11:59:30Z", now), "now");
  assert.equal(relativeTime("2026-10-17T11:15:00Z", now), "45 min");
  assert.equal(relativeTime("2026-10-17T02:00:00Z", now), "10 h");
  assert.equal(relativeTime("2026-10-14T12:00:00Z", now), "3 d");
  assert.equal(relativeTime("2026-10-03T12:00:00Z", now), "3 Oct");
  assert.equal(relativeTime("2025-12-24T12:00:00Z", now), "24 Dec 2025");
  assert.equal(relativeTime(null, now), "");
  assert.equal(relativeTime("not a date", now), "");
});

test("a saved post opens on its gallery when it has one", () => {
  assert.equal(savedPath([{ kind: "image", id: "4" }, { kind: "gallery", id: "9" }]), "galleries/9");
  assert.equal(savedPath([{ kind: "scene", id: "2" }]), "scenes/2");
  assert.equal(savedPath([{ kind: "image", id: "4" }]), "images/4");
  assert.equal(savedPath([]), null);
});

test("the Explore box understands tags, creators and links", () => {
  assert.deepEqual(parseSearch("#Beach "), { kind: "tag", value: "Beach" });
  assert.deepEqual(parseSearch("dry humping"), { kind: "tag", value: "dry humping" });
  assert.deepEqual(parseSearch("@sunny-days"), { kind: "creator", value: "sunny-days" });
  assert.deepEqual(parseSearch("https://imaglr.com/profile/some%20one"), { kind: "creator", value: "some one" });
  assert.deepEqual(parseSearch("https://imaglr.com/post/96040950?x=1"), { kind: "post", value: "96040950" });
  assert.deepEqual(parseSearch("96040950"), { kind: "post", value: "96040950" });
  assert.equal(parseSearch("  "), null);
  assert.equal(parseSearch("@"), null);
  assert.equal(parseSearch("#"), null);
});

test("space kept for media before it loads, and short counts", () => {
  assert.equal(mediaRatio({ kind: "image", url: "", thumb: null, mime: null, width: 400, height: 200 }), 2);
  assert.equal(mediaRatio({ kind: "video", url: "", thumb: null, mime: null, width: null, height: null }), 0.8);
  assert.equal(shortCount(999), "999");
  assert.equal(shortCount(1200), "1.2k");
  assert.equal(shortCount(3000), "3k");
  assert.equal(shortCount(45600), "46k");
});

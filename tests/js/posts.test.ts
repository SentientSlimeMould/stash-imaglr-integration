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

test("a broken imaglr avatar address has a working twin", async () => {
  const { avatarFallback } = await import("../../src/ui/lib/posts.ts");
  assert.equal(avatarFallback("https://cdn03.imaglr.com/storage/avatars/2026/7/1/a.webp"), "https://cdn03.imaglr.com/avatars/2026/7/1/a.webp");
  assert.equal(avatarFallback("https://cdn03.imaglr.com/avatars/2026/7/1/a.webp"), null); // already fine
  assert.equal(avatarFallback("https://ui-avatars.com/api/?name=x"), null);
  assert.equal(avatarFallback(null), null);
});

test("Explore remembers searches and offers them before the creators you follow", async () => {
  const { exploreOptions, rememberSearch, searchLabel, RECENT_SEARCHES } = await import("../../src/ui/lib/posts.ts");
  assert.equal(searchLabel({ kind: "tag", value: "wam" }, "#wam "), "#wam");
  assert.equal(searchLabel({ kind: "creator", value: "sunny" }, "https://imaglr.com/profile/sunny"), "@sunny");
  assert.equal(searchLabel({ kind: "post", value: "123" }, " https://imaglr.com/post/123 "), "https://imaglr.com/post/123");
  let recent = rememberSearch([], "#wam");
  recent = rememberSearch(recent, "@sunny");
  recent = rememberSearch(recent, "#WAM"); // again, whatever the case: to the front, once
  assert.deepEqual(recent, ["#WAM", "@sunny"]);
  for (let n = 0; n < 20; n++) recent = rememberSearch(recent, `#t${n}`);
  assert.equal(recent.length, RECENT_SEARCHES);

  const people = [{ name: "sunny", avatar: null }, { name: "ocean", avatar: "https://cdn03.imaglr.com/o.jpg" }];
  const empty = exploreOptions("", ["@sunny", "#wam"], people);
  assert.deepEqual(empty.map((g) => g.label), ["Recent searches", "People you follow"]);
  assert.deepEqual(empty[1].options.map((o) => o.value), ["@ocean"]); // @sunny is already a recent search
  const typed = exploreOptions("su", ["@sunny", "#wam", "#sunset"], people);
  assert.deepEqual(typed[0].options[0], { value: "su", label: "Search #su", kind: "search" });
  assert.deepEqual(typed[1].options.map((o) => o.value), ["@sunny", "#sunset"]);
  assert.equal(typed.length, 2); // sunny is in the recent searches already
  assert.equal(exploreOptions("@oc", [], people)[0].options[0].label, "Go to @oc");
  assert.equal(exploreOptions("@oc", [], people)[1].options[0].avatar, "https://cdn03.imaglr.com/o.jpg");
  assert.equal(exploreOptions("https://imaglr.com/post/5", [], [])[0].options[0].label, "Open this post");
});

test("the imaglr credit is read from an item's URLs", async () => {
  const { imaglrCredit } = await import("../../src/ui/lib/posts.ts");
  assert.deepEqual(imaglrCredit(["https://imaglr.com/post/96040950", "https://imaglr.com/profile/some%20one"]),
    { postUrl: "https://imaglr.com/post/96040950", postId: "96040950", creatorUrl: "https://imaglr.com/profile/some%20one", creator: "some one" });
  assert.equal(imaglrCredit(["https://example.com/post/1"]), null);
  assert.equal(imaglrCredit([]), null);
  assert.equal(imaglrCredit(undefined), null);
  assert.equal(imaglrCredit(["https://imaglr.com/post/5"])?.creator, null);
});

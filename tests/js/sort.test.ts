// SPDX-License-Identifier: AGPL-3.0-only
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  applyControls, cardWidth, DEFAULTS, filterCount, formatsIn, loadControls, orientationOf, saveControls,
} from "../../src/ui/lib/sort.ts";
import type { Candidate } from "../../src/ui/lib/types.ts";

type Img = Candidate & { id: string };
const img = (o: Partial<Img>): Img => ({
  id: "1", title: "a", width: 100, height: 100, bytes: 10, format: "JPG", created_at: "2026-01-01T00:00:00Z",
  date: null, first_seen: "2026-01-01T00:00:00Z", item: null, ...o,
});
const clip = (o: Partial<Img>): Img => ({
  id: "1", title: "c", scene_title: "", duration: 5, bytes: 1, width: 1920, height: 1080, format: "MP4",
  created_at: null, date: null, first_seen: "2026-01-02T00:00:00Z", item: null, ...o,
});
const ids = (list: Img[]) => list.map((c) => c.id);

const list = [
  img({ id: "1", title: "zebra", bytes: 5, format: "GIF", first_seen: "2026-01-01T00:00:00Z", width: 200, height: 113,
    created_at: "2025-06-01T00:00:00Z", date: "2020-01-01" }),
  img({ id: "2", title: "apple", bytes: 50, format: "JPG", first_seen: "2026-01-03T00:00:00Z", width: 1000, height: 2000,
    created_at: "2025-01-01T00:00:00Z", date: null }),
  img({ id: "3", title: "mango", bytes: 20, format: "WEBP", first_seen: "2026-01-02T00:00:00Z", width: 500, height: 500,
    created_at: "2025-03-01T00:00:00Z", date: "2024-01-01", item: { status: "ready" } }),
];

test("defaults to newest added first", () => {
  assert.deepEqual(ids(applyControls(list, DEFAULTS)), ["2", "3", "1"]);
});

test("added falls back to created when first-seen is missing", () => {
  const l = [img({ id: "a", first_seen: null, created_at: "2026-02-01T00:00:00Z" }), img({ id: "b" })];
  assert.deepEqual(ids(applyControls(l, DEFAULTS)), ["a", "b"]);
});

test("sorts by name asc, size desc, type", () => {
  assert.deepEqual(applyControls(list, { ...DEFAULTS, sort: "name", dir: "asc" }).map((c) => c.title), ["apple", "mango", "zebra"]);
  assert.deepEqual(applyControls(list, { ...DEFAULTS, sort: "size", dir: "desc" }).map((c) => c.bytes), [50, 20, 5]);
  assert.deepEqual(applyControls(list, { ...DEFAULTS, sort: "type", dir: "asc" }).map((c) => c.format), ["GIF", "JPG", "WEBP"]);
});

test("sorts by created, date and resolution", () => {
  assert.deepEqual(ids(applyControls(list, { ...DEFAULTS, sort: "created", dir: "asc" })), ["2", "3", "1"]);
  // no date sorts as oldest
  assert.deepEqual(ids(applyControls(list, { ...DEFAULTS, sort: "date", dir: "desc" })), ["3", "1", "2"]);
  assert.deepEqual(ids(applyControls(list, { ...DEFAULTS, sort: "dims", dir: "desc" })), ["2", "3", "1"]);
});

test("filters by type, status, orientation and search", () => {
  assert.deepEqual(ids(applyControls(list, { ...DEFAULTS, types: ["GIF", "WEBP"] })), ["3", "1"]);
  assert.deepEqual(ids(applyControls(list, { ...DEFAULTS, status: "ready" })), ["3"]);
  assert.deepEqual(ids(applyControls(list, { ...DEFAULTS, status: "untouched" })), ["2", "1"]);
  assert.deepEqual(ids(applyControls(list, { ...DEFAULTS, orientation: "portrait" })), ["2"]);
  assert.deepEqual(ids(applyControls(list, { ...DEFAULTS, orientation: "landscape" })), ["1"]);
  assert.deepEqual(ids(applyControls(list, { ...DEFAULTS, orientation: "square" })), ["3"]);
  assert.deepEqual(ids(applyControls(list, { ...DEFAULTS, search: "MAN" })), ["3"]);
});

test("sorts clips by length and searches scene titles", () => {
  const clips = [clip({ id: "a", duration: 30, scene_title: "Beach day" }), clip({ id: "b", duration: 5 })];
  assert.deepEqual(ids(applyControls(clips, { ...DEFAULTS, sort: "length", dir: "asc" })), ["b", "a"]);
  assert.deepEqual(ids(applyControls(clips, { ...DEFAULTS, search: " beach " })), ["a"]);
});

test("helpers", () => {
  assert.deepEqual(formatsIn(list), ["GIF", "JPG", "WEBP"]);
  assert.equal(orientationOf(img({ width: 500, height: 505 })), "square");
  assert.equal(orientationOf(img({ width: null, height: null })), "any");
});

test("controls are saved per tab and merged over defaults", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
  assert.deepEqual(loadControls("images", storage), DEFAULTS);
  saveControls("images", { ...DEFAULTS, sort: "name", zoom: 3 }, storage);
  assert.deepEqual([...store.keys()], ["imaglr.controls.images"]);
  assert.equal(loadControls("images", storage).sort, "name");
  assert.equal(loadControls("clips", storage).sort, "added");
  store.set("imaglr.controls.clips", "{not json");
  assert.deepEqual(loadControls("clips", storage), DEFAULTS);
});

test("status can be read straight from a card", () => {
  const cards = [img({ id: "a", status: "failed" }), img({ id: "b", status: "ready" })];
  assert.deepEqual(ids(applyControls(cards, { ...DEFAULTS, status: "failed" })), ["a"]);
});

test("filter count and card width follow Stash", () => {
  assert.equal(filterCount(DEFAULTS), 0);
  assert.equal(filterCount({ ...DEFAULTS, status: "failed", orientation: "portrait" }), 2);
  assert.equal(cardWidth(0, 1), 340);
  assert.equal(Math.round(cardWidth(1230, 1)), 290); // 4 per row in a 1200px usable width
});

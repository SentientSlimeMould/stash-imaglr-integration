// SPDX-License-Identifier: AGPL-3.0-only
import { test } from "node:test";
import assert from "node:assert/strict";
import { displayedRect, normCrop, overlayRect } from "../../src/ui/lib/crop.ts";

function close(actual: number, expected: number, digits: number) {
  assert.ok(Math.abs(actual - expected) < 10 ** -digits / 2, `${actual} is not close to ${expected}`);
}

test("normCrop crops width for landscape → 9:16", () => {
  const n = normCrop(1920, 1080, "9:16", 0.5);
  assert.equal(n.axis, "x");
  assert.equal(n.h, 1);
  close(n.w, 0.3164, 3);
  close(n.x, (1 - n.w) / 2, 6);
});

test("normCrop crops height for portrait → 1:1", () => {
  const n = normCrop(1080, 1920, "1:1", 0);
  assert.equal(n.axis, "y");
  assert.equal(n.w, 1);
  close(n.h, 0.5625, 4);
  assert.equal(n.y, 0);
  close(normCrop(1080, 1920, "1:1", 1).y, 1 - 0.5625, 4);
});

test("normCrop does not crop when the aspect matches or is original", () => {
  assert.equal(normCrop(1080, 1920, "9:16", 0.5).axis, "none");
  assert.deepEqual(normCrop(1920, 1080, "original", 0.5), { x: 0, y: 0, w: 1, h: 1, axis: "none" });
});

test("normCrop clamps position", () => {
  close(normCrop(1920, 1080, "1:1", 5).x, 1 - 1080 / 1920, 6);
  assert.equal(normCrop(1920, 1080, "1:1", -1).x, 0);
});

test("displayedRect letterboxes a 16:9 video in a square container", () => {
  const r = displayedRect(400, 400, 1920, 1080);
  assert.equal(r.dw, 400);
  close(r.dh, 225, 3);
  close(r.dy, 87.5, 3);
});

test("overlayRect lies inside the displayed media", () => {
  const o = overlayRect(400, 400, 1920, 1080, "1:1", 1);
  close(o.width, 225, 3);
  close(o.left + o.width, 400, 3);
  close(o.top, 87.5, 3);
});

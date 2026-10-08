// SPDX-License-Identifier: AGPL-3.0-only
import { test } from "node:test";
import assert from "node:assert/strict";
import { displayedRect, hasEdges, insetRect, normCrop, overlayRect } from "../../src/ui/lib/crop.ts";

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
  assert.deepEqual(normCrop(1920, 1080, "original", 0.5), { x: 0, y: 0, w: 1, h: 1, axis: "none", cropped: false });
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

test("edge trims cut the picture first and the aspect applies inside", () => {
  const edges = { top: 0.1, bottom: 0.1, left: 0, right: 0 };
  const n = normCrop(1920, 1080, "original", 0.5, edges);
  assert.deepEqual(n, { x: 0, y: 0.1, w: 1, h: 0.8, axis: "none", cropped: true });
  // 1920x864 left after the bars is wider than 1:1: the square is 864 px wide, centred within the trimmed box
  const sq = normCrop(1920, 1080, "1:1", 0.5, edges);
  assert.equal(sq.axis, "x");
  close(sq.w, 864 / 1920, 6);
  close(sq.h, 0.8, 6);
  close(sq.y, 0.1, 6);
  close(sq.x, (1 - 864 / 1920) / 2, 6);
  assert.equal(sq.cropped, true);
});

test("edge trims are bounded and keep a tenth of each dimension", () => {
  const r = insetRect({ top: 0.9, bottom: 0.9, left: -1, right: 0 });
  assert.equal(r.x, 0);
  assert.equal(r.w, 1);
  close(r.y, 0.45, 6);
  close(r.h, 0.1, 6);
  assert.equal(hasEdges(null), false);
  assert.equal(hasEdges({ top: 0, bottom: 0, left: 0, right: 0 }), false);
  assert.equal(hasEdges({ top: 0.02, bottom: 0, left: 0, right: 0 }), true);
});

test("overlay marks the trimmed picture even with the original aspect", () => {
  const r = overlayRect(400, 225, 1920, 1080, "original", 0.5, { top: 0.1, bottom: 0.1, left: 0, right: 0 });
  assert.equal(r.cropped, true);
  close(r.top, 22.5, 3);
  close(r.height, 180, 3);
  assert.equal(overlayRect(400, 225, 1920, 1080, "original", 0.5, null).cropped, false);
});

test("the crop section's summary names what is set", async () => {
  const { cropSummary } = await import("../../src/ui/lib/crop.ts");
  assert.equal(cropSummary({ aspect: "original" }), "");
  assert.equal(cropSummary({ aspect: "1:1" }), "1:1");
  assert.equal(cropSummary({ aspect: "original", edges: { top: 0.1, bottom: 0, left: 0, right: 0 } }), "edges trimmed");
  assert.equal(cropSummary({ aspect: "9:16", edges: { top: 0.1, bottom: 0, left: 0, right: 0 } }), "9:16 · edges trimmed");
});

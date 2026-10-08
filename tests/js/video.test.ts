// SPDX-License-Identifier: AGPL-3.0-only
import { test } from "node:test";
import assert from "node:assert/strict";
import { edgeLabel, outputEdge, sizeChoicesFor, videoEstimate } from "../../src/ui/lib/video.ts";

test("picture size labels and the output edge never exceed the source or 1080p", () => {
  assert.equal(edgeLabel(1920), "1080p");
  assert.equal(edgeLabel(1280), "720p");
  assert.equal(edgeLabel(854), "480p");
  assert.equal(outputEdge(3840, null), 1920);
  assert.equal(outputEdge(1280, null), 1280);
  assert.equal(outputEdge(1920, 1280), 1280);
  assert.equal(outputEdge(640, 1280), 640);
  assert.equal(outputEdge(null, 854), 854);
});

test("a short clip gets a plain size estimate", () => {
  const e = videoEstimate(30, "h264", 1920);
  assert.equal(e.warn, false);
  assert.match(e.text, /^About 2\d MB as H\.264 at 1080p\.$/);
  assert.match(videoEstimate(30, "hevc", 1280, true).text, /^About \d+ MB as H\.265 at 720p\.$/);
});

test("a long clip is warned about, with advice that fits the choices made", () => {
  const seven = videoEstimate(420, "h264", 1920);
  assert.equal(seven.warn, true);
  assert.match(seven.text, /encoded at about 1\.7 Mbit\/s as H\.264 at 1080p, which will look poor\. Choose a smaller picture or H\.265\./);
  const hevc720 = videoEstimate(420, "hevc", 1280);
  assert.equal(hevc720.warn, false);
  assert.match(hevc720.text, /should still look fine/);
  assert.match(videoEstimate(420, "hevc", 1920).text, /Choose a smaller picture\./);
  assert.match(videoEstimate(1200, "h264", 854).text, /Choose H\.265 or a shorter clip\./);
  assert.match(videoEstimate(1200, "hevc", 854).text, /Choose a shorter clip\./);
});

test("only picture sizes smaller than the source are offered", () => {
  assert.deepEqual(sizeChoicesFor(1920).map((o) => o.label), ["Original", "720p", "480p"]);
  assert.deepEqual(sizeChoicesFor(1280).map((o) => o.label), ["Original", "480p"]);
  assert.deepEqual(sizeChoicesFor(320).map((o) => o.label), ["Original"]);
  assert.deepEqual(sizeChoicesFor(null).map((o) => o.label), ["Original", "720p", "480p"]);
});

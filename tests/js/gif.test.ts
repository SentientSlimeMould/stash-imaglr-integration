// SPDX-License-Identifier: AGPL-3.0-only
import assert from "node:assert/strict";
import { test } from "node:test";
import { describeGifEstimate, estimateGifMb, gifSeconds, LONG_GIF_SECONDS } from "../../src/ui/lib/gif.ts";
import { gifCounts } from "../../src/ui/lib/sendAll.ts";

test("estimate scales with length and reads as a band", () => {
  assert.deepEqual(estimateGifMb(10), [12, 30]);
  assert.equal(describeGifEstimate(10), "roughly 10–30 MB");
  assert.equal(describeGifEstimate(3), "roughly 4–9 MB");
  assert.equal(describeGifEstimate(0), "roughly 0 MB");
  assert.equal(LONG_GIF_SECONDS, 15);
});

test("a boomerang plays twice as long, so weighs twice as much", () => {
  assert.equal(gifSeconds(5, "boomerang"), 10);
  assert.deepEqual(estimateGifMb(5, "boomerang"), estimateGifMb(10));
  assert.equal(describeGifEstimate(5, "boomerang"), describeGifEstimate(10));
});

test("gif counts ignore skipped items", () => {
  const plan = [
    { id: "a", gif: true, long_gif: true },
    { id: "b", gif: true },
    { id: "c", gif: true, long_gif: true, skip: "busy" },
    { id: "d" },
  ];
  assert.deepEqual(gifCounts(plan), { gifs: 2, long: 1 });
});

test("a smaller GIF picture scales the estimate by area and is only offered below the source width", async () => {
  const { gifSizeChoicesFor } = await import("../../src/ui/lib/gif.ts");
  const [lo698] = estimateGifMb(10);
  const [lo480] = estimateGifMb(10, "forward", 480);
  assert.ok(Math.abs(lo480 / lo698 - (480 * 480) / (698 * 698)) < 1e-9);
  assert.deepEqual(gifSizeChoicesFor(1920).map((o) => o.label), ["Original", "480 px", "320 px"]);
  assert.deepEqual(gifSizeChoicesFor(400).map((o) => o.label), ["Original", "320 px"]);
  assert.deepEqual(gifSizeChoicesFor(null).map((o) => o.label), ["Original", "480 px", "320 px"]);
});

test("a WebP of the same clip is estimated at about a third of the GIF", () => {
  const [gLo, gHi] = estimateGifMb(10);
  const [wLo, wHi] = estimateGifMb(10, "forward", null, "webp");
  assert.ok(Math.abs(wLo / gLo - 0.35) < 1e-9 && Math.abs(wHi / gHi - 0.35) < 1e-9);
  assert.equal(describeGifEstimate(10, "forward", null, "webp"), "roughly 4–10 MB");
});

test("frame rates are offered up to the source's own and scale the estimate", async () => {
  const { fpsChoicesFor } = await import("../../src/ui/lib/gif.ts");
  assert.deepEqual(fpsChoicesFor(29.97).map((o) => o.label), ["Auto", "30 fps (source)", "24 fps", "15 fps", "10 fps"]);
  assert.deepEqual(fpsChoicesFor(24).map((o) => o.label), ["Auto", "24 fps (source)", "15 fps", "10 fps"]);
  assert.deepEqual(fpsChoicesFor(12).map((o) => o.label), ["Auto", "12 fps (source)", "10 fps"]);
  assert.deepEqual(fpsChoicesFor(null).map((o) => o.label), ["Auto"]);
  const [lo15] = estimateGifMb(10);
  const [lo30] = estimateGifMb(10, "forward", null, "gif", 30);
  assert.ok(Math.abs(lo30 / lo15 - 2) < 1e-9);
});

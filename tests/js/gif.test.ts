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

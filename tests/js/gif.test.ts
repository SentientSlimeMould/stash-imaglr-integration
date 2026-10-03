// SPDX-License-Identifier: AGPL-3.0-only
import assert from "node:assert/strict";
import { test } from "node:test";
import { describeGifEstimate, estimateGifMb, LONG_GIF_SECONDS } from "../../src/ui/lib/gif.ts";
import { gifCounts } from "../../src/ui/lib/sendAll.ts";

test("estimate scales with length and reads as a band", () => {
  assert.deepEqual(estimateGifMb(10), [10, 25]);
  assert.equal(describeGifEstimate(10), "roughly 10–25 MB");
  assert.equal(describeGifEstimate(3), "roughly 3–8 MB");
  assert.equal(describeGifEstimate(0), "roughly 0 MB");
  assert.equal(LONG_GIF_SECONDS, 15);
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

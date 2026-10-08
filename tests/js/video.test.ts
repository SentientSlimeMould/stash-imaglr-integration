// SPDX-License-Identifier: AGPL-3.0-only
import { test } from "node:test";
import assert from "node:assert/strict";
import { LONG_VIDEO_SECONDS, longVideoNotice } from "../../src/ui/lib/video.ts";

test("only long videos get the upload-limit notice", () => {
  assert.equal(longVideoNotice(30), null);
  assert.equal(longVideoNotice(LONG_VIDEO_SECONDS), null);
  assert.match(longVideoNotice(420)!, /^A 7-minute video has to be reduced to fit imaglr's 100 MB upload limit\./);
  assert.match(longVideoNotice(420)!, /H\.265/);
});

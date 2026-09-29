// SPDX-License-Identifier: AGPL-3.0-only
import { test } from "node:test";
import assert from "node:assert/strict";
import { addedMessage, galleryIdFromPath } from "../../src/ui/lib/imageActions.ts";

test("gallery id comes from the gallery page URL, with or without a proxy prefix", () => {
  assert.equal(galleryIdFromPath("/galleries/12/images"), "12");
  assert.equal(galleryIdFromPath("/stash/galleries/7"), "7");
  assert.equal(galleryIdFromPath("/images"), null);
});

test("messages count images plainly", () => {
  assert.equal(addedMessage({ added: 1, already: 0, post_id: null }, false), "1 image added to imaglr.");
  assert.equal(
    addedMessage({ added: 2, already: 1, post_id: null }, false),
    "2 images added to imaglr. 1 image already there.",
  );
  assert.equal(addedMessage({ added: 3, already: 1, post_id: "p" }, true), "4 images added to imaglr as one post.");
});

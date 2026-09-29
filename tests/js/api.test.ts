// SPDX-License-Identifier: AGPL-3.0-only
import { test } from "node:test";
import assert from "node:assert/strict";
import { baseUrl } from "../../src/ui/api.ts";

function docWithBase(href: string | null): Document {
  const base = href === null ? null : { getAttribute: () => href };
  return { querySelector: () => base } as unknown as Document;
}

test("base URL defaults to the site root", () => {
  assert.equal(baseUrl(docWithBase(null)), "/");
});

test("base URL keeps a reverse-proxy prefix and ends with a slash", () => {
  assert.equal(baseUrl(docWithBase("/stash/")), "/stash/");
  assert.equal(baseUrl(docWithBase("/stash")), "/stash/");
});

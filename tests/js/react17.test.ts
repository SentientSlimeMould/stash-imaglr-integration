// SPDX-License-Identifier: AGPL-3.0-only
// Stash ships React 17 up to v0.31.x and React 18 from v0.32.0, and the plugin runs on both. Its types are
// React 18's, so the compiler would accept an API that doesn't exist on React 17 and fails there at runtime:
// this test catches those instead. Remove it once v0.31.x is no longer supported (docs/stash-plugin-facts.md §10).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const UI = new URL("../../src/ui/", import.meta.url).pathname;
const REACT_18_ONLY = /\b(useId|useTransition|startTransition|useDeferredValue|useSyncExternalStore|useInsertionEffect|createRoot|hydrateRoot|ReactDOMClient|flushSync)\b/;

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? sources(join(dir, e.name)) : /\.tsx?$/.test(e.name) && !e.name.endsWith(".d.ts") ? [join(dir, e.name)] : []);
}

test("the UI uses nothing React 18 adds, so it still runs on Stash v0.31.x", () => {
  const found = sources(UI).flatMap((file) =>
    readFileSync(file, "utf8").split("\n").flatMap((line, i) =>
      REACT_18_ONLY.test(line.replace(/\/\/.*$/, "")) ? [`${file.slice(UI.length)}:${i + 1}: ${line.trim()}`] : []));
  assert.deepEqual(found, []);
});

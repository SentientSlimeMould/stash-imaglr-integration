// SPDX-License-Identifier: AGPL-3.0-only
// imaglr tag rules for the editor: 30 tags per post, 64 characters each, case-insensitive duplicates.

import type { Suggestions } from "./types.ts";

export const MAX_TAGS = 30;
export const MAX_LEN = 64;

export function normalise(name: string, lowercase: boolean): string {
  const s = name.trim().replace(/\s+/g, " ");
  return lowercase ? s.toLowerCase() : s;
}

// ---- the Stash-style tag field (src/ui/editor/TagField.tsx) works on plain lists of tag names ----

export type TagCheck = { ok: true; tag: string } | { ok: false; error: string };

/** Whether a typed tag can be added to `tags`, and in what form it will be sent. */
export function checkNewTag(tags: string[], raw: string, lowercase: boolean): TagCheck {
  const tag = normalise(raw, lowercase);
  if (!tag) return { ok: false, error: "Empty tag" };
  if (tag.length > MAX_LEN) return { ok: false, error: `Tags can be at most ${MAX_LEN} characters` };
  if (tags.some((t) => t.toLowerCase() === tag.toLowerCase())) return { ok: false, error: "Already added" };
  if (tags.length >= MAX_TAGS) return { ok: false, error: `imaglr allows ${MAX_TAGS} tags per post` };
  return { ok: true, tag };
}

/** Where "Add <what you typed>" goes among the suggestions. First, so Enter adds exactly what you typed,
 *  unless a suggestion starts with it: then you are probably completing that one ("vint" → "vintage"), and
 *  it stays first. A suggestion that merely contains the text ("dry humping" for "humping") doesn't count. */
export function addOptionFirst(typed: string, suggestions: string[]): boolean {
  const q = typed.toLowerCase();
  return !suggestions.some((s) => s.toLowerCase().startsWith(q));
}

/** Suggested tags not currently on the post, split into ones that can be added and ones that can't. */
export function spareSuggestions(s: Suggestions | undefined, tags: string[]) {
  const taken = new Set(tags.map((t) => t.toLowerCase()));
  const all = [...(s?.active ?? []), ...(s?.greyed ?? [])].filter((t) => !taken.has(t.tag.toLowerCase()));
  const unique = all.filter((t, i) => all.findIndex((o) => o.tag.toLowerCase() === t.tag.toLowerCase()) === i);
  return {
    addable: unique.filter((t) => t.reason !== "too_long").map((t) => t.tag),
    tooLong: unique.filter((t) => t.reason === "too_long").map((t) => t.original || t.tag),
  };
}

// SPDX-License-Identifier: AGPL-3.0-only
// Tag chips for the tag editor: 30 tags per post, 64 characters each, case-insensitive duplicates.

import type { Suggestions, TagChip } from "./types.ts";

export const MAX_TAGS = 30;
export const MAX_LEN = 64;

export function normalise(name: string, lowercase: boolean): string {
  const s = name.trim().replace(/\s+/g, " ");
  return lowercase ? s.toLowerCase() : s;
}

/** Chips from the backend's suggestions; `selected` is the item's saved tag list (null = not yet edited). */
export function chipsFromSuggestions(s: Suggestions | undefined, selected: string[] | null): TagChip[] {
  const chips: TagChip[] = [];
  const seen = new Set<string>();
  const sel = selected ? new Set(selected.map((t) => t.toLowerCase())) : null;
  for (const t of s?.active ?? []) {
    seen.add(t.tag.toLowerCase());
    const on = sel ? sel.has(t.tag.toLowerCase()) : true;
    chips.push({ name: t.tag, source: t.source, state: on ? "active" : "parked", reason: on ? undefined : "removed", original: t.original });
  }
  for (const t of s?.greyed ?? []) {
    if (seen.has(t.tag.toLowerCase())) continue;
    seen.add(t.tag.toLowerCase());
    if (t.reason === "too_long") {
      chips.push({ name: t.tag, source: t.source, state: "too_long", reason: `over ${MAX_LEN} characters`, original: t.original });
    } else {
      const on = sel ? sel.has(t.tag.toLowerCase()) : false;
      chips.push({
        name: t.tag, source: t.source, state: on ? "active" : "parked",
        reason: on ? undefined : `over the ${MAX_TAGS}-tag limit`, original: t.original,
      });
    }
  }
  // tags saved on the item that are not in the suggestions (manual additions)
  for (const t of selected ?? []) {
    if (!seen.has(t.toLowerCase())) {
      seen.add(t.toLowerCase());
      chips.push({ name: t, source: "manual", state: "active" });
    }
  }
  return chips;
}

export function activeNames(chips: TagChip[]): string[] {
  return chips.filter((c) => c.state === "active").map((c) => c.name);
}

export type AddResult = { ok: true; chips: TagChip[]; parked: boolean } | { ok: false; error: string; existing?: string };

/** Adds a typed tag; a duplicate of a parked chip re-activates it, and past the limit the new chip is parked. */
export function addTag(chips: TagChip[], raw: string, lowercase: boolean): AddResult {
  const name = normalise(raw, lowercase);
  if (!name) return { ok: false, error: "Empty tag" };
  if (name.length > MAX_LEN) return { ok: false, error: `Tag is ${name.length} characters; the limit is ${MAX_LEN}` };
  const dup = chips.find((c) => c.name.toLowerCase() === name.toLowerCase());
  if (dup) {
    if (dup.state === "active") return { ok: false, error: "Already added", existing: dup.name };
    if (dup.state === "too_long") return { ok: false, error: "That tag is too long", existing: dup.name };
    return activate(chips, dup.name);
  }
  const room = activeNames(chips).length < MAX_TAGS;
  const chip: TagChip = room
    ? { name, source: "manual", state: "active" }
    : { name, source: "manual", state: "parked", reason: `over the ${MAX_TAGS}-tag limit` };
  return { ok: true, chips: [...chips, chip], parked: !room };
}

export function activate(chips: TagChip[], name: string): AddResult {
  if (activeNames(chips).length >= MAX_TAGS) return { ok: false, error: `Remove a tag first (limit ${MAX_TAGS})` };
  return {
    ok: true, parked: false,
    chips: chips.map((c) => (c.name === name && c.state !== "too_long" ? { ...c, state: "active", reason: undefined } : c)),
  };
}

/** Suggested chips are parked so they can be re-added; manual chips are dropped. */
export function removeTag(chips: TagChip[], name: string): TagChip[] {
  return chips
    .map((c) => (c.name === name ? (c.source === "manual" ? null : { ...c, state: "parked" as const, reason: "removed" }) : c))
    .filter((c): c is TagChip => c !== null);
}

/** Renames a chip (keeping its original name) or drops it when `next` is null or would duplicate another chip. */
export function replaceChip(chips: TagChip[], name: string, next: string | null): TagChip[] {
  if (next === null) return chips.filter((c) => c.name !== name);
  const dup = chips.some((c) => c.name.toLowerCase() === next.toLowerCase() && c.name !== name);
  if (dup) return chips.filter((c) => c.name !== name);
  return chips.map((c) => (c.name === name ? { ...c, name: next, original: c.original ?? c.name } : c));
}

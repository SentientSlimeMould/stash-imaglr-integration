// SPDX-License-Identifier: AGPL-3.0-only
// Sort, filter and view controls for the Clips and Images tabs.

import type { Candidate, Status } from "./types.ts";

export type SortKey = "added" | "name" | "size" | "length" | "type" | "created" | "date" | "dims";
export type Dir = "asc" | "desc";
export type Orientation = "any" | "portrait" | "landscape" | "square";
export type StatusFilter = "all" | "untouched" | Status;

export type ViewMode = "grid" | "list";

/** Stash's image-card widths for its zoom slider (ui/v2.5/src/components/Images/ImageCardGrid.tsx). */
export const ZOOM_WIDTHS = [280, 340, 480, 640];

export interface QueueControlsState {
  sort: SortKey;
  dir: Dir;
  search: string;
  status: StatusFilter;
  types: string[]; // upper-case formats, empty = all
  orientation: Orientation;
  view: ViewMode;
  zoom: number; // index into ZOOM_WIDTHS, like Stash's zoom slider
  perPage: number;
}

export const DEFAULTS: QueueControlsState = {
  sort: "added", dir: "desc", search: "", status: "all", types: [], orientation: "any",
  view: "grid", zoom: 1, perPage: 40,
};

/** Stash's page-size choices (ui/v2.5/src/components/List/ListFilter.tsx). */
export const PAGE_SIZES = [20, 40, 60, 120, 250, 500, 1000];

/** The items on one page, and the page actually shown (clamped when the list shrinks). */
export function paginate<T>(list: T[], page: number, perPage: number): { items: T[]; page: number; pages: number } {
  const size = Math.max(1, perPage);
  const pages = Math.max(1, Math.ceil(list.length / size));
  const current = Math.min(Math.max(1, page), pages);
  return { items: list.slice((current - 1) * size, current * size), page: current, pages };
}

export const SORTS: Record<"clips" | "images", { key: SortKey; label: string }[]> = {
  clips: [
    { key: "added", label: "Added" }, { key: "name", label: "Name" }, { key: "length", label: "Length" },
    { key: "size", label: "File size" }, { key: "created", label: "Created in Stash" },
    { key: "date", label: "Scene date" }, { key: "dims", label: "Resolution" },
  ],
  images: [
    { key: "added", label: "Added" }, { key: "name", label: "Name" }, { key: "type", label: "File type" },
    { key: "size", label: "File size" }, { key: "created", label: "Created in Stash" },
    { key: "date", label: "Image date" }, { key: "dims", label: "Resolution" },
  ],
};

function num(v: unknown): number { return typeof v === "number" && isFinite(v) ? v : -1; }
function str(v: unknown): string { return typeof v === "string" ? v.toLowerCase() : ""; }
function ts(v: unknown): number { const t = typeof v === "string" ? Date.parse(v) : NaN; return isNaN(t) ? -1 : t; }
function pixels(c: Candidate): number { return num(c.width) > 0 && num(c.height) > 0 ? num(c.width) * num(c.height) : -1; }

function keyOf(c: Candidate, key: SortKey): number | string {
  switch (key) {
    case "added": return ts(c.first_seen) >= 0 ? ts(c.first_seen) : ts(c.created_at);
    case "name": return str(c.title);
    case "size": return num(c.bytes);
    case "length": return num(c.duration);
    case "type": return str(c.format);
    case "created": return ts(c.created_at);
    case "date": return ts(c.date);
    case "dims": return pixels(c);
  }
}

export function orientationOf(c: Candidate): Orientation {
  const w = num(c.width), h = num(c.height);
  if (w <= 0 || h <= 0) return "any";
  if (Math.abs(w - h) / Math.max(w, h) < 0.02) return "square";
  return w > h ? "landscape" : "portrait";
}

export function applyControls<T extends Candidate>(list: T[], s: QueueControlsState): T[] {
  const q = s.search.trim().toLowerCase();
  const out = list.filter((c) => {
    if (q && !`${c.title} ${c.scene_title ?? ""}`.toLowerCase().includes(q)) return false;
    if (s.status !== "all") {
      const st = c.status ?? c.item?.status ?? null;
      if (s.status === "untouched" ? st !== null : st !== s.status) return false;
    }
    if (s.types.length && !s.types.includes((c.format ?? "").toUpperCase())) return false;
    if (s.orientation !== "any" && orientationOf(c) !== s.orientation) return false;
    return true;
  });
  const mult = s.dir === "asc" ? 1 : -1;
  return out.sort((a, b) => {
    const ka = keyOf(a, s.sort), kb = keyOf(b, s.sort);
    let r = typeof ka === "string" && typeof kb === "string" ? ka.localeCompare(kb) : (ka as number) - (kb as number);
    if (r === 0) r = ts(b.first_seen) - ts(a.first_seen); // stable secondary: newest added first
    return r * mult;
  });
}

/** Upper-case formats present in the list, most common first (for the type filter). */
export function formatsIn(list: Candidate[]): string[] {
  const counts = new Map<string, number>();
  for (const c of list) {
    const f = (c.format ?? "").toUpperCase();
    if (f) counts.set(f, (counts.get(f) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([f]) => f);
}

type ControlsStorage = Pick<Storage, "getItem" | "setItem">;

const storageKey = (tab: string) => `imaglr.controls.${tab}`;

/** Saved controls for a tab; defaults when nothing is saved or storage is unavailable. */
export function loadControls(tab: string, storage?: ControlsStorage): QueueControlsState {
  try {
    const raw = (storage ?? localStorage).getItem(storageKey(tab));
    if (raw) {
      const saved = { ...DEFAULTS, ...JSON.parse(raw) } as QueueControlsState;
      saved.zoom = Math.min(Math.max(Number(saved.zoom) || 0, 0), ZOOM_WIDTHS.length - 1);
      saved.perPage = Math.max(1, Math.floor(Number(saved.perPage))) || DEFAULTS.perPage;
      return saved;
    }
  } catch { /* ignore */ }
  return { ...DEFAULTS };
}

export function saveControls(tab: string, s: QueueControlsState, storage?: ControlsStorage): void {
  try { (storage ?? localStorage).setItem(storageKey(tab), JSON.stringify(s)); } catch { /* ignore */ }
}

/** Number of active filters, shown on the Filter button like Stash does. */
export function filterCount(s: QueueControlsState): number {
  return (s.status !== "all" ? 1 : 0) + (s.types.length ? 1 : 0) + (s.orientation !== "any" ? 1 : 0);
}

/**
 * Card width in px for a container, following Stash's own calculateCardWidth
 * (ui/v2.5/src/components/Shared/GridCard/GridCard.tsx): fill each row evenly near the preferred width.
 */
export function cardWidth(containerWidth: number, zoom: number): number {
  const preferred = ZOOM_WIDTHS[zoom] ?? ZOOM_WIDTHS[1];
  if (!containerWidth) return preferred;
  const usable = containerWidth - 30;
  return usable / Math.ceil(usable / preferred) - 10;
}

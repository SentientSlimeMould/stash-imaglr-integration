// SPDX-License-Identifier: AGPL-3.0-only
// Crop rectangles for the fixed output aspects, in source and on-screen space.

import type { Aspect, CropEdges } from "./types.ts";

export const ASPECTS: Record<Aspect, number | null> = { original: null, "9:16": 9 / 16, "4:5": 4 / 5, "1:1": 1 };
export type Axis = "x" | "y" | "none";

export const EDGE_NAMES = ["top", "bottom", "left", "right"] as const;
export const MAX_EDGE_PERCENT = 45; // the same bound as the backend's clean_edges

export function emptyEdges(): CropEdges {
  return { top: 0, right: 0, bottom: 0, left: 0 };
}

/** What the crop is set to, for the collapsed section's header: "1:1 · edges trimmed"; empty when nothing is cropped. */
export function cropSummary(crop: { aspect: Aspect; edges?: CropEdges | null }): string {
  const parts: string[] = [];
  if (crop.aspect !== "original") parts.push(crop.aspect);
  if (hasEdges(crop.edges)) parts.push("edges trimmed");
  return parts.join(" · ");
}

export function hasEdges(edges: CropEdges | null | undefined): boolean {
  return !!edges && EDGE_NAMES.some((n) => (edges[n] ?? 0) > 0);
}

/** The picture left after the edge trims, as fractions of the source; at least a tenth of each dimension. */
export function insetRect(edges: CropEdges | null | undefined): { x: number; y: number; w: number; h: number } {
  const e = edges ?? emptyEdges();
  const clamp = (v: number) => Math.min(MAX_EDGE_PERCENT / 100, Math.max(0, v || 0));
  const l = clamp(e.left), t = clamp(e.top);
  const w = Math.max(0.1, 1 - l - clamp(e.right)), h = Math.max(0.1, 1 - t - clamp(e.bottom));
  return { x: l, y: t, w, h };
}

export interface NormCrop { x: number; y: number; w: number; h: number; axis: Axis; cropped: boolean }

/** Normalised crop rect in source space (0..1): the edge trims, then the aspect inside what is left.
 *  position 0 = left/top, 1 = right/bottom along the axis the aspect crops. */
export function normCrop(srcW: number, srcH: number, aspect: Aspect, position: number, edges?: CropEdges | null): NormCrop {
  const box = insetRect(edges);
  const trimmed = box.x > 0 || box.y > 0 || box.w < 1 || box.h < 1;
  const a = ASPECTS[aspect];
  if (a == null || srcW <= 0 || srcH <= 0) return { ...box, axis: "none", cropped: trimmed };
  const s = (srcW * box.w) / (srcH * box.h);
  if (Math.abs(s - a) < 1e-6) return { ...box, axis: "none", cropped: trimmed };
  let w = 1, h = 1;
  if (a < s) w = a / s; else h = s / a;
  const p = Math.min(1, Math.max(0, position));
  return {
    x: box.x + (1 - w) * p * box.w, y: box.y + (1 - h) * p * box.h, w: w * box.w, h: h * box.h,
    axis: w < 1 ? "x" : h < 1 ? "y" : "none", cropped: true,
  };
}

export interface DisplayedRect { dx: number; dy: number; dw: number; dh: number }

/** Where the media is drawn inside a container using object-fit: contain. */
export function displayedRect(cw: number, ch: number, srcW: number, srcH: number): DisplayedRect {
  if (srcW <= 0 || srcH <= 0 || cw <= 0 || ch <= 0) return { dx: 0, dy: 0, dw: cw, dh: ch };
  const scale = Math.min(cw / srcW, ch / srcH);
  const dw = srcW * scale, dh = srcH * scale;
  return { dx: (cw - dw) / 2, dy: (ch - dh) / 2, dw, dh };
}

export interface OverlayRect { left: number; top: number; width: number; height: number; axis: Axis; cropped: boolean }

/** The crop rect in container pixels, for drawing over the displayed media. */
export function overlayRect(
  cw: number, ch: number, srcW: number, srcH: number, aspect: Aspect, position: number, edges?: CropEdges | null,
): OverlayRect {
  const { dx, dy, dw, dh } = displayedRect(cw, ch, srcW, srcH);
  const n = normCrop(srcW, srcH, aspect, position, edges);
  return { left: dx + n.x * dw, top: dy + n.y * dh, width: n.w * dw, height: n.h * dh, axis: n.axis, cropped: n.cropped };
}

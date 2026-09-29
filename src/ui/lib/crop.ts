// SPDX-License-Identifier: AGPL-3.0-only
// Crop rectangles for the fixed output aspects, in source and on-screen space.

import type { Aspect } from "./types.ts";

export const ASPECTS: Record<Aspect, number | null> = { original: null, "9:16": 9 / 16, "4:5": 4 / 5, "1:1": 1 };
export type Axis = "x" | "y" | "none";

export interface NormCrop { x: number; y: number; w: number; h: number; axis: Axis }

/** Normalised crop rect in source space (0..1). position 0 = left/top, 1 = right/bottom. */
export function normCrop(srcW: number, srcH: number, aspect: Aspect, position: number): NormCrop {
  const a = ASPECTS[aspect];
  if (a == null || srcW <= 0 || srcH <= 0) return { x: 0, y: 0, w: 1, h: 1, axis: "none" };
  const s = srcW / srcH;
  if (Math.abs(s - a) < 1e-6) return { x: 0, y: 0, w: 1, h: 1, axis: "none" };
  let w = 1, h = 1;
  if (a < s) w = a / s; else h = s / a;
  const p = Math.min(1, Math.max(0, position));
  return { x: (1 - w) * p, y: (1 - h) * p, w, h, axis: w < 1 ? "x" : h < 1 ? "y" : "none" };
}

export interface DisplayedRect { dx: number; dy: number; dw: number; dh: number }

/** Where the media is drawn inside a container using object-fit: contain. */
export function displayedRect(cw: number, ch: number, srcW: number, srcH: number): DisplayedRect {
  if (srcW <= 0 || srcH <= 0 || cw <= 0 || ch <= 0) return { dx: 0, dy: 0, dw: cw, dh: ch };
  const scale = Math.min(cw / srcW, ch / srcH);
  const dw = srcW * scale, dh = srcH * scale;
  return { dx: (cw - dw) / 2, dy: (ch - dh) / 2, dw, dh };
}

export interface OverlayRect { left: number; top: number; width: number; height: number; axis: Axis }

/** The crop rect in container pixels, for drawing over the displayed media. */
export function overlayRect(
  cw: number, ch: number, srcW: number, srcH: number, aspect: Aspect, position: number,
): OverlayRect {
  const { dx, dy, dw, dh } = displayedRect(cw, ch, srcW, srcH);
  const n = normCrop(srcW, srcH, aspect, position);
  return { left: dx + n.x * dw, top: dy + n.y * dh, width: n.w * dw, height: n.h * dh, axis: n.axis };
}

// SPDX-License-Identifier: AGPL-3.0-only
// What a clip would roughly weigh as an animated GIF, for the editor's estimate. GIF size depends on how much
// moves, so this is a band, not a number: measured on real footage at 640 px / 15 fps, ordinary video runs
// about 1-2.5 MB per second, scaled here to the first ladder rung (698 px wide, imaglr's feed width).

export const GIF_TARGET_MB_DEFAULT = 20;
export const GIF_HARD_LIMIT_MB = 40;
export const LONG_GIF_SECONDS = 15;

const MB_PER_SECOND = { low: 1.2, high: 3.0 };

export type GifLoop = "forward" | "boomerang";

/** How long the GIF plays for: a boomerang runs the clip forward then back. */
export function gifSeconds(seconds: number, loop: GifLoop = "forward"): number {
  return Math.max(0, seconds) * (loop === "boomerang" ? 2 : 1);
}

/** [low, high] MB for a clip of this length at the first rung. */
export function estimateGifMb(seconds: number, loop: GifLoop = "forward"): [number, number] {
  const s = gifSeconds(seconds, loop);
  return [s * MB_PER_SECOND.low, s * MB_PER_SECOND.high];
}

function roundMb(n: number): number {
  return n < 10 ? Math.round(n) : Math.round(n / 5) * 5;
}

/** "roughly 15–25 MB" with the band rounded to friendly numbers. */
export function describeGifEstimate(seconds: number, loop: GifLoop = "forward"): string {
  const [lo, hi] = estimateGifMb(seconds, loop).map(roundMb);
  return lo === hi ? `roughly ${lo} MB` : `roughly ${lo}–${hi} MB`;
}

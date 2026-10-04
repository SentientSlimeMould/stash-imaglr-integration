// SPDX-License-Identifier: AGPL-3.0-only
// What a clip would roughly weigh as an animated GIF, for the editor's estimate. GIF size depends on how much
// moves, so this is a band, not a number: measured on real footage at the plugin's first ladder rung
// (640 px, 15 fps), ordinary video runs about 1-2.5 MB per second.

export const GIF_TARGET_MB_DEFAULT = 20;
export const GIF_HARD_LIMIT_MB = 40;
export const LONG_GIF_SECONDS = 15;

const MB_PER_SECOND = { low: 1.0, high: 2.5 };

/** [low, high] MB for a clip of this length at the first rung. */
export function estimateGifMb(seconds: number): [number, number] {
  const s = Math.max(0, seconds);
  return [s * MB_PER_SECOND.low, s * MB_PER_SECOND.high];
}

function roundMb(n: number): number {
  return n < 10 ? Math.round(n) : Math.round(n / 5) * 5;
}

/** "roughly 15–25 MB" with the band rounded to friendly numbers. */
export function describeGifEstimate(seconds: number): string {
  const [lo, hi] = estimateGifMb(seconds).map(roundMb);
  return lo === hi ? `roughly ${lo} MB` : `roughly ${lo}–${hi} MB`;
}

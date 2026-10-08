// SPDX-License-Identifier: AGPL-3.0-only
// What a clip would roughly weigh as an animated GIF, for the editor's estimate. GIF size depends on how much
// moves, so this is a band, not a number: measured on real footage at 640 px / 15 fps, ordinary video runs
// about 1-2.5 MB per second, scaled here to the first ladder rung (698 px wide, imaglr's feed width).

export const GIF_TARGET_MB_DEFAULT = 20;
export const GIF_HARD_LIMIT_MB = 40;
export const LONG_GIF_SECONDS = 15;

const MB_PER_SECOND = { low: 1.2, high: 3.0 };

export type GifLoop = "forward" | "boomerang";
export type AnimatedFormat = "gif" | "webp";
const WEBP_FACTOR = 0.35; // an animated WebP of the same clip is usually a third to a half of the GIF's size

export const GIF_FEED_WIDTH = 698; // imaglr's feed width: the ladder's top rung
/** The GIF picture sizes offered: the feed width, or smaller; widths in px (null = the feed width). */
export const GIF_SIZE_OPTIONS: { label: string; value: number | null }[] = [
  { label: "Original", value: null }, { label: "480 px", value: 480 }, { label: "320 px", value: 320 },
];

/** The sizes worth offering for a source this wide (never upscaled). */
export function gifSizeChoicesFor(sourceWidth: number | null): typeof GIF_SIZE_OPTIONS {
  return GIF_SIZE_OPTIONS.filter((o) => o.value === null || !sourceWidth || o.value < sourceWidth);
}

export const LADDER_FPS = 15; // the top rung's frame rate, which the estimate is measured at

/** The frame rates worth offering for a source at `sourceFps`: the source's own, then the usual steps below it.
 *  Null (Auto) is always first and means the ladder's own rate. */
export function fpsChoicesFor(sourceFps: number | null): { label: string; value: number | null }[] {
  const out: { label: string; value: number | null }[] = [{ label: "Auto", value: null }];
  if (!sourceFps || sourceFps <= 0) return out;
  const source = Math.min(60, Math.round(sourceFps));
  const steps = [source, 30, 24, 15, 10].filter((f, i, a) => f <= source && f >= 5 && a.indexOf(f) === i);
  for (const f of steps) out.push({ label: f === source ? `${f} fps (source)` : `${f} fps`, value: f });
  return out;
}

/** How a smaller picture scales the estimate: by area. */
function widthFactor(width: number | null): number {
  const w = Math.min(width ?? GIF_FEED_WIDTH, GIF_FEED_WIDTH);
  return (w * w) / (GIF_FEED_WIDTH * GIF_FEED_WIDTH);
}

/** How long the GIF plays for: a boomerang runs the clip forward then back. */
export function gifSeconds(seconds: number, loop: GifLoop = "forward"): number {
  return Math.max(0, seconds) * (loop === "boomerang" ? 2 : 1);
}

/** [low, high] MB for a clip of this length at the first rung it may use. */
export function estimateGifMb(seconds: number, loop: GifLoop = "forward", width: number | null = null, format: AnimatedFormat = "gif",
                              fps: number | null = null): [number, number] {
  const s = gifSeconds(seconds, loop) * widthFactor(width) * (format === "webp" ? WEBP_FACTOR : 1) * ((fps ?? LADDER_FPS) / LADDER_FPS);
  return [s * MB_PER_SECOND.low, s * MB_PER_SECOND.high];
}

function roundMb(n: number): number {
  return n < 10 ? Math.round(n) : Math.round(n / 5) * 5;
}

/** "roughly 15–25 MB" with the band rounded to friendly numbers. */
export function describeGifEstimate(seconds: number, loop: GifLoop = "forward", width: number | null = null, format: AnimatedFormat = "gif",
                                    fps: number | null = null): string {
  const [lo, hi] = estimateGifMb(seconds, loop, width, format, fps).map(roundMb);
  return lo === hi ? `roughly ${lo} MB` : `roughly ${lo}–${hi} MB`;
}

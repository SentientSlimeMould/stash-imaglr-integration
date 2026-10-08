// SPDX-License-Identifier: AGPL-3.0-only
// What a clip sent as a video is up against: imaglr allows 500 MB per video (large files travel in pieces, so
// the edge's 100 MB cap on one request no longer bites), and the plugin encodes at the bitrate that fits. The
// user picks the codec and the picture size; this estimates the outcome so they can decide. Mirrors the
// backend's ffmpeg_cmd tables.

export type Codec = "h264" | "hevc";

export const VIDEO_CAP_MB = 500;
export const CODEC_LABELS: Record<Codec, string> = { h264: "H.264", hevc: "H.265" };
/** The picture-size choices: a long edge in px, or null for "as the source (up to 1080p)". */
export const SIZE_OPTIONS: { label: string; value: number | null }[] = [
  { label: "Original", value: null }, { label: "720p", value: 1280 }, { label: "480p", value: 854 },
];
/** The picture sizes worth offering: Original, plus only the sizes smaller than the source (never upscaled). */
export function sizeChoicesFor(sourceEdge: number | null): typeof SIZE_OPTIONS {
  return SIZE_OPTIONS.filter((o) => o.value === null || !sourceEdge || o.value < sourceEdge);
}

const TYPICAL_KBPS: [number, number][] = [[1920, 6000], [1280, 3000], [854, 1500], [640, 900]];
const FLOOR_KBPS: [number, number][] = [[1920, 4000], [1280, 2000], [854, 1000], [640, 600]];
const HEVC_FACTOR = 0.6;
const AUDIO_KBPS = 128;

function lookup(table: [number, number][], longEdge: number, codec: Codec): number {
  const row = table.find(([edge]) => edge <= longEdge) ?? table[table.length - 1];
  return Math.round(row[1] * (codec === "hevc" ? HEVC_FACTOR : 1));
}

/** "1080p", "720p", … for a long edge, as people say it. */
export function edgeLabel(longEdge: number): string {
  if (longEdge >= 1920) return "1080p";
  if (longEdge >= 1280) return "720p";
  if (longEdge >= 854) return "480p";
  return `${longEdge} px`;
}

/** The picture's long edge after the size choice: never larger than the source, never above 1080p. */
export function outputEdge(sourceEdge: number | null, maxEdge: number | null): number {
  return Math.min(sourceEdge || 1920, maxEdge ?? 1920, 1920);
}

export interface VideoEstimate {
  text: string; // e.g. "About 45 MB as H.264 at 1080p."
  short: string; // for a section header, e.g. "about 45 MB" or "about 1.7 Mbit/s, will look poor"
  warn: boolean; // the budget is too thin for this picture: suggest a smaller one or H.265
}

/** Rough size of the clip with these choices, and whether it will have to be squeezed to fit the limit. */
export function videoEstimate(seconds: number, codec: Codec, longEdge: number, muted = false): VideoEstimate {
  const s = Math.max(0, seconds);
  const audio = muted ? 0 : AUDIO_KBPS;
  const typical = lookup(TYPICAL_KBPS, longEdge, codec);
  const usualMb = ((typical + audio) * s) / 8192;
  const label = `${CODEC_LABELS[codec]} at ${edgeLabel(longEdge)}`;
  if (usualMb <= VIDEO_CAP_MB * 0.95 || s === 0) {
    const mb = usualMb < 10 ? Math.max(1, Math.round(usualMb)) : Math.round(usualMb / 5) * 5;
    return { text: `About ${mb} MB as ${label}.`, short: `about ${mb} MB`, warn: false };
  }
  const budget = Math.max(200, Math.round((VIDEO_CAP_MB * 8192 * 0.95) / s - audio));
  const floor = lookup(FLOOR_KBPS, longEdge, codec);
  const rate = budget >= 1000 ? `${(budget / 1000).toFixed(1)} Mbit/s` : `${budget} kbit/s`;
  if (budget >= floor) {
    return { text: `Over ${VIDEO_CAP_MB} MB at the usual quality, so it will be encoded at about ${rate} as ${label}, which should still look fine.`, short: `about ${rate}, fine`, warn: false };
  }
  const advice = codec === "h264" && longEdge > 854 ? "Choose a smaller picture or H.265."
    : longEdge > 854 ? "Choose a smaller picture." : codec === "h264" ? "Choose H.265 or a shorter clip." : "Choose a shorter clip.";
  return { text: `Over ${VIDEO_CAP_MB} MB at the usual quality, so it will be encoded at about ${rate} as ${label}, which will look poor. ${advice}`, short: `about ${rate}, will look poor`, warn: true };
}

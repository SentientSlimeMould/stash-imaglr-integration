// SPDX-License-Identifier: AGPL-3.0-only
// Pure helpers for the clip editor: which Stash stream to play, and keeping in/out points sane.

export interface SceneStream {
  url: string;
  mime_type: string | null;
  label: string | null;
}

export interface VideoInfo {
  video_codec?: string | null;
  format?: string | null;
}

const DIRECT_CODECS: Record<string, string> = { h264: "avc1.42E01E", vp8: "vp8", vp9: "vp9", av1: "av01.0.05M.08", hevc: "hvc1" };
const CONTAINER_MIME: Record<string, string> = { mp4: "video/mp4", m4v: "video/mp4", mov: "video/mp4", webm: "video/webm" };

/** The MIME type (with codec) to ask the browser about, or null if the container can't play directly at all. */
export function directMime(info: VideoInfo): string | null {
  const container = CONTAINER_MIME[(info.format ?? "").toLowerCase()];
  const codec = DIRECT_CODECS[(info.video_codec ?? "").toLowerCase()];
  return container && codec ? `${container}; codecs="${codec}"` : null;
}

/**
 * The URL to play: Stash's direct stream when this browser can play the file as it is, otherwise
 * Stash's MP4 transcode (e.g. HEVC or MKV sources on most browsers).
 */
export function pickStream(
  direct: string,
  streams: SceneStream[],
  info: VideoInfo,
  canPlay: (mime: string) => boolean,
): string {
  const mime = directMime(info);
  if (mime && canPlay(mime)) return direct;
  const mp4 = streams.find((s) => (s.mime_type ?? "").startsWith("video/mp4") && !/direct/i.test(s.label ?? ""));
  return mp4?.url ?? direct;
}

/** Same path and query on this page's origin: Stash may build URLs for another host name or scheme. */
export function sameOrigin(url: string, origin: string): string {
  const u = new URL(url, origin);
  return origin + u.pathname + u.search;
}

export const MIN_CLIP = 0.1;

/** Clamp in/out to the video, keeping out after in; `moved` says which end the user changed. */
export function clampTrim(inS: number, outS: number, duration: number | null, moved: "in" | "out") {
  const max = duration && duration > 0 ? duration : Number.POSITIVE_INFINITY;
  let a = Math.max(0, Math.min(inS, max));
  let b = Math.max(0, Math.min(outS, max));
  if (b - a < MIN_CLIP) {
    if (moved === "in") a = Math.max(0, b - MIN_CLIP);
    else b = Math.min(max, a + MIN_CLIP);
  }
  return { inS: Math.round(a * 1000) / 1000, outS: Math.round(b * 1000) / 1000 };
}

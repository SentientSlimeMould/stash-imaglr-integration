// SPDX-License-Identifier: AGPL-3.0-only
// What a clip sent as a video is up against: imaglr's API refuses any upload over 100 MB (measured; its
// documentation says 500 MB), so a long clip is encoded to fit. Up to about three minutes the usual quality
// fits at 1080p; past that the plugin switches to H.265 and then lowers the resolution.

export const VIDEO_CAP_MB = 100;
export const LONG_VIDEO_SECONDS = 180;

/** The notice shown under the Format choice for a video of this length, or null when it needs none. */
export function longVideoNotice(seconds: number): string | null {
  if (!(seconds > LONG_VIDEO_SECONDS)) return null;
  const minutes = Math.round(seconds / 60);
  return `A ${minutes}-minute video has to be reduced to fit imaglr's ${VIDEO_CAP_MB} MB upload limit. ` +
    "The plugin uses H.265, then a smaller picture, to keep it watchable.";
}

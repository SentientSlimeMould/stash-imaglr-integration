// SPDX-License-Identifier: AGPL-3.0-only
// Shapes returned by the plugin backend's queue operations (imaglr_integration/services.py).
import type { Status } from "./lib/types.ts";

export type Kind = "image" | "clip" | "still" | "set";
export type SendAction = "draft" | "queue" | "publish";

export interface Card {
  id: string;
  kind: Kind;
  title: string;
  status: Status;
  progress: number;
  error_code: string | null;
  error_detail: string | null;
  blog_id: number | null;
  action: SendAction | null;
  tag_count: number;
  send_format?: "video" | "gif" | "webp"; // clips: how it will be sent
  send_codec?: "h264" | "hevc";
  max_edge?: number | null; // picture size as a long edge; null = as the source
  loop?: "forward" | "boomerang"; // GIFs: forward, or forward then back
  gif_width?: number | null; // GIFs: picture width in px; null = the feed width
  gif_fps?: number | null; // GIFs and WebPs: frame rate; null = the ladder's own
  fps?: number | null; // clips: the source's frame rate
  output_note?: string | null; // after preparing: e.g. "GIF · 9.4 MB · 480 px · 10 fps"
  thumb: string | null; // relative to Stash's base URL
  width?: number | null;
  height?: number | null;
  bytes?: number | null;
  format?: string | null;
  animated?: boolean;
  duration?: number | null;
  created_at?: string | null;
  date?: string | null;
  first_seen?: string | null;
  stash_image_id?: string | null;
  stash_marker_id?: string | null;
  stash_scene_id?: string | null;
  whole_scene?: boolean; // a clip cut from a scene shared whole, with no marker behind it
  scene_duration?: number | null;
  tab?: "clips" | "images";
  preview?: string | null; // clips: Stash's marker preview video
  in_s?: number | null;
  out_s?: number | null;
  members?: Card[]; // posts with several files
}

export interface QueueResponse {
  items: Card[];
  tags: { queue: { id: string; name: string }; done: { id: string; name: string } };
  sent_count: number;
}

export const STATUS_LABELS: Record<Status, string> = {
  pending: "New",
  exporting: "Preparing",
  ready: "Ready",
  sending: "Sending",
  sent: "Sent",
  failed: "Failed",
};

export const STATUS_VARIANTS: Record<Status, string> = {
  pending: "secondary",
  exporting: "info",
  ready: "success",
  sending: "info",
  sent: "primary",
  failed: "danger",
};

export interface Blog {
  id: number;
  label: string;
  name: string | null;
  url: string | null;
  key_hint: string;
  ok: boolean;
  supporter: boolean | null;
  nsfw: boolean | null;
  default_action: SendAction;
  error_code: string | null;
  error_detail: string | null;
  paused_reason: string | null;
  checked_at: string | null;
  limits?: Record<string, { limit: number; remaining: number }> | null;
}

export interface FileCard extends Card {
  image?: string | null;
  crop: import("./lib/types.ts").Crop;
  in_s: number | null;
  out_s: number | null;
  mute: boolean;
  flip: boolean;
  format: "video" | "gif" | "webp";
  codec: "h264" | "hevc";
  max_edge: number | null; // picture size as a long edge (1280 = 720p, 854 = 480p); null = as the source
  loop: "forward" | "boomerang";
  gif_width: number | null;
  gif_fps: number | null;
  output_note: string | null; // what the prepared file turned out to be, e.g. "GIF · 9.4 MB · 480 px · 10 fps"
  output_mime: string | null; // of the prepared file, e.g. "image/gif"
  stash_marker_id: string | null;
  stash_scene_id: string | null;
  stash_image_id: string | null;
  prepared: string | null;
}

export interface ItemDetail {
  item: {
    id: string;
    kind: Kind;
    status: Status;
    tags: string[];
    caption: string;
    blog_id: number | null;
    action: SendAction | null;
    crop: import("./lib/types.ts").Crop;
    error_code: string | null;
    error_detail: string | null;
    progress: number;
    source_title: string;
    in_s: number | null;
    out_s: number | null;
    mute: boolean;
    flip: boolean;
    format: "video" | "gif" | "webp";
    codec: "h264" | "hevc";
    max_edge: number | null;
    loop: "forward" | "boomerang";
    gif_width: number | null;
    gif_fps: number | null;
    output_note: string | null;
    hdr_warning: boolean;
    updated_at: string; // changes whenever the item (and so its prepared file) does: busts the browser's cache
    tags_auto: boolean; // tags still follow Stash and the tag rules (never edited)
  };
  files: FileCard[];
  suggestions: import("./lib/types.ts").Suggestions;
  blogs: Blog[];
  lowercase_tags: boolean;
  queue_tag: string;
  gif_target_mb: number;
}

export interface SentFile {
  id: string;
  kind: Kind;
  title: string;
  thumb: string | null;
  thumb_fallback: string | null; // shown if the thumbnail can't load: a clip's scene screenshot (its marker may be gone)
  in_s: number | null;
  stash_image_id: string | null;
  stash_scene_id: string | null;
  stash_marker_id: string | null;
}

export interface SentItem {
  id: string;
  kind: Kind;
  title: string;
  files: SentFile[];
  thumb: string | null;
  thumb_fallback: string | null;
  blog_id: number | null;
  blog: string | null;
  sent_as: SendAction;
  sent_at: string;
  draft_id: string | null;
  post_url: string | null;
  tags: string[];
  caption: string;
  dropped_tags: string[];
  dropped?: { tag: string; from: string | null }[]; // detail only: the Stash name each dropped tag came from
  output_note?: string | null; // e.g. "GIF · 9.4 MB · 480 px · 10 fps", or why a GIF went as a video
  followup_failed: boolean;
  action: SendAction | null;
  error_code: string | null;
  error_detail: string | null;
}

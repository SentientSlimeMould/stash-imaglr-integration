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
  members?: Card[]; // posts with several files
}

export interface QueueResponse {
  items: Card[];
  tags: { queue: { id: string; name: string }; done: { id: string; name: string } };
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
  image: string | null;
  crop: { aspect: import("./lib/types.ts").Aspect; position: number };
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
    crop: { aspect: import("./lib/types.ts").Aspect; position: number };
    error_code: string | null;
    error_detail: string | null;
    progress: number;
    source_title: string;
  };
  files: FileCard[];
  suggestions: import("./lib/types.ts").Suggestions;
  blogs: Blog[];
  lowercase_tags: boolean;
}

export interface SentItem {
  id: string;
  kind: Kind;
  title: string;
  files: number;
  thumb: string | null;
  blog: string | null;
  sent_as: SendAction;
  sent_at: string;
  draft_id: string | null;
  post_url: string | null;
  tags: string[];
  dropped_tags: string[];
  followup_failed: boolean;
  action: SendAction | null;
  error_code: string | null;
  error_detail: string | null;
  stash_image_ids: string[];
}

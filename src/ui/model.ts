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

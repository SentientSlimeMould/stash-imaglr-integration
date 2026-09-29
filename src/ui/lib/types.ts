// SPDX-License-Identifier: AGPL-3.0-only
// Shapes used by the pure UI helpers in this folder. Kept to the fields the helpers read.

export type Status = "pending" | "exporting" | "ready" | "sending" | "sent" | "failed";
export type Aspect = "original" | "9:16" | "4:5" | "1:1";

/** A tile on the Clips or Images tab: a Stash marker/image plus the plugin's item state, if any. */
export interface Candidate {
  title: string;
  scene_title?: string | null;
  width?: number | null;
  height?: number | null;
  bytes?: number | null;
  format?: string | null;
  duration?: number | null; // clips only
  created_at?: string | null;
  date?: string | null;
  first_seen?: string | null;
  status?: Status;
  item?: { status: Status } | null;
}

export interface SuggestedTag {
  tag: string;
  source: string;
  original: string;
  reason: "too_long" | "over_limit" | null;
}

export interface Suggestions {
  active: SuggestedTag[];
  greyed: SuggestedTag[];
}

export interface TagChip {
  name: string;
  source: string;
  state: "active" | "parked" | "too_long";
  reason?: string;
  original?: string;
}

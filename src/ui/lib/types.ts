// SPDX-License-Identifier: AGPL-3.0-only
// Shapes used by the pure UI helpers in this folder. Kept to the fields the helpers read.

export type Status = "pending" | "exporting" | "ready" | "sending" | "sent" | "failed";
export type Aspect = "original" | "9:16" | "4:5" | "1:1";

/** Fractions (0..1) of the picture cut off each side, e.g. black bars. */
export interface CropEdges { top: number; right: number; bottom: number; left: number }

export interface Crop {
  aspect: Aspect;
  position: number; // 0..1 along the axis the aspect crops
  edges?: CropEdges | null; // trimmed first; the aspect applies inside what is left
}

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

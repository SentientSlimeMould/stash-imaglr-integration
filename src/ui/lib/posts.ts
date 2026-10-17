// SPDX-License-Identifier: AGPL-3.0-only
// imaglr posts as the Discover section shows them (the backend's browse_ops/saving.normalize_post), and the
// small pure helpers the feed uses: how long ago, where a saved post lives in Stash, what a search means.

export interface Creator {
  name: string;
  url: string | null;
  avatar: string | null;
}

export interface CreatorProfile extends Creator {
  description: string;
  counts: { followers: number; following: number; posts: number };
}

export interface PostMedia {
  kind: "image" | "video";
  url: string;
  thumb: string | null;
  mime: string | null;
  width: number | null;
  height: number | null;
}

export interface StashRef {
  kind: "scene" | "image" | "gallery";
  id: string;
}

export interface SaveState {
  post_id: string;
  status: "queued" | "downloading" | "scanning" | "done" | "failed";
  progress: number;
  error: string | null;
  refs: StashRef[];
}

export interface ImaglrPost {
  id: string;
  url: string | null;
  type: string;
  created_at: string | null;
  summary: string;
  tags: string[];
  nsfw: boolean;
  creator: Creator;
  original: { id: string; url: string | null; creator: Creator } | null; // set when this is a reblog
  media: PostMedia[];
  notes: { likes: number; reposts: number; comments: number };
  liked: boolean;
  credit_id: string; // the post a save is credited to: the original, for a reblog
  saved: StashRef[]; // what the user's Stash already holds of it
  save: SaveState | null; // a save under way, or one that failed
}

export interface BrowsePage {
  posts: ImaglrPost[];
  next: string | null;
  profile: CreatorProfile | null;
  blog: { id: number; name: string | null };
}

export type BrowseSource = "feed" | "likes" | "tag" | "creator";

export const SAVING = ["queued", "downloading", "scanning"];

/** "now", "5 min", "3 h", "2 d", then the date ("12 Oct", with the year when it isn't this year). */
export function relativeTime(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "";
  const then = new Date(iso);
  const seconds = (now.getTime() - then.getTime()) / 1000;
  if (Number.isNaN(seconds)) return "";
  if (seconds < 60) return "now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
  if (seconds < 7 * 86400) return `${Math.floor(seconds / 86400)} d`;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const day = `${then.getUTCDate()} ${months[then.getUTCMonth()]}`;
  return then.getUTCFullYear() === now.getUTCFullYear() ? day : `${day} ${then.getUTCFullYear()}`;
}

/** Where a saved post is in Stash (a path under Stash's base): its gallery when it has several files. */
export function savedPath(refs: StashRef[]): string | null {
  const ref = refs.find((r) => r.kind === "gallery") ?? refs[0];
  if (!ref) return null;
  return `${ref.kind === "gallery" ? "galleries" : ref.kind === "scene" ? "scenes" : "images"}/${ref.id}`;
}

/** What a search box entry means: "@name" a creator, "#tag" or words a tag, an imaglr post link or number a post. */
export function parseSearch(text: string): { kind: "creator" | "tag" | "post"; value: string } | null {
  const value = text.trim();
  if (!value) return null;
  const link = value.match(/imaglr\.[a-z.]+\/post\/(\d+)/i) ?? value.match(/^(\d{3,})$/);
  if (link) return { kind: "post", value: link[1] };
  const profile = value.match(/imaglr\.[a-z.]+\/profile\/([^/?#\s]+)/i);
  if (profile) return { kind: "creator", value: decodeURIComponent(profile[1]) };
  if (value.startsWith("@")) return value.length > 1 ? { kind: "creator", value: value.slice(1).trim() } : null;
  const tag = value.replace(/^#/, "").trim();
  return tag ? { kind: "tag", value: tag } : null;
}

/** The space a picture or video takes before it loads, so the feed doesn't jump: width / height, or 4:5. */
export function mediaRatio(m: PostMedia): number {
  return m.width && m.height ? m.width / m.height : 4 / 5;
}

/** imaglr's API gives uploaded avatars an address on its CDN with an extra "/storage" that the CDN answers 404
 *  for (seen 2026-10-17); the same file is at that address without it. The other address to try, or null. */
export function avatarFallback(url: string | null): string | null {
  if (!url) return null;
  const fixed = url.replace(/^(https:\/\/cdn\d{0,3}\.imaglr\.com)\/storage\/avatars\//, "$1/avatars/");
  return fixed === url ? null : fixed;
}

/** "1.2k" for counts. */
export function shortCount(n: number): string {
  if (n < 1000) return String(n);
  if (n < 10000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return `${Math.round(n / 1000)}k`;
}

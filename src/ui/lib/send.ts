// SPDX-License-Identifier: AGPL-3.0-only
// Which blog and action a send will use, and how to say so on the button.
import type { Blog, SendAction } from "../model.ts";

/** What a post becomes on imaglr ("Send as …"); the Sent tab's badges use the same words. */
export const ACTION_LABELS: Record<SendAction, string> = {
  draft: "Draft",
  queue: "Queued",
  publish: "Published",
};

export const SENT_AS_LABELS: Record<SendAction, string> = {
  draft: "Draft",
  queue: "Queued",
  publish: "Published",
};

/** The item's chosen blog, else the only blog; null when the user must choose. */
export function pickBlog(blogs: Blog[], blogId: number | null): Blog | null {
  if (blogId != null) return blogs.find((b) => b.id === blogId) ?? null;
  return blogs.length === 1 ? blogs[0] : null;
}

/** The action chosen for this send, else the blog's default. */
export function effectiveAction(blog: Blog | null, action: SendAction | null): SendAction {
  return action ?? blog?.default_action ?? "draft";
}

export function sendButtonLabel(action: SendAction, blog: Blog | null): string {
  if (!blog) return "Choose a blog";
  const name = blog.name ?? blog.label;
  if (action === "publish") return `Publish now on ${name}`;
  if (action === "queue") return `Add to ${name}'s queue`;
  return `Save draft to ${name}`;
}

/** Why a blog can't be sent to right now, in plain words; null when it can. */
export function blogProblem(blog: Blog): string | null {
  if (blog.paused_reason === "premium_required" || blog.supporter === false) {
    return "imaglr's API needs a paid supporter account.";
  }
  if (blog.paused_reason === "account_suspended") return "imaglr has suspended this account.";
  if (!blog.ok && blog.error_code) return blog.error_detail || blog.error_code;
  return null;
}

/** imaglr page to open after sending: drafts live on the drafts page; queued and published posts have URLs. */
export function imaglrLink(sentAs: SendAction, postUrl: string | null): string {
  if (sentAs === "draft" || !postUrl) return "https://imaglr.com/drafts";
  return postUrl;
}

/**
 * The Stash page a file came from: the image, or the scene for a clip. Stash has no page for one marker and
 * no way to open a scene on its Markers tab from a link, so a clip links to the scene playing from the
 * clip's start (?t=<seconds>).
 */
export function stashLink(f: { stash_image_id?: string | null; stash_scene_id?: string | null; in_s?: number | null }): string | null {
  if (f.stash_image_id) return `/images/${f.stash_image_id}`;
  if (f.stash_scene_id) return `/scenes/${f.stash_scene_id}${f.in_s ? `?t=${Math.floor(f.in_s)}` : ""}`;
  return null;
}

// SPDX-License-Identifier: AGPL-3.0-only
// Which blog and action a send will use, and how to say so on the button.
import type { Blog, SendAction } from "../model.ts";

export const ACTION_LABELS: Record<SendAction, string> = {
  draft: "Save as draft",
  queue: "Add to queue",
  publish: "Publish now",
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

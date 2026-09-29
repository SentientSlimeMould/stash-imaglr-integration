// SPDX-License-Identifier: AGPL-3.0-only
import { test } from "node:test";
import assert from "node:assert/strict";
import { blogProblem, effectiveAction, imaglrLink, pickBlog, sendButtonLabel } from "../../src/ui/lib/send.ts";
import type { Blog } from "../../src/ui/model.ts";

const blog = (id: number, over: Partial<Blog> = {}): Blog => ({
  id, label: `blog-${id}`, name: `blog-${id}`, url: null, key_hint: "pbk_…abcd", ok: true, supporter: true,
  nsfw: false, default_action: "draft", error_code: null, error_detail: null, paused_reason: null, checked_at: null,
  ...over,
});

test("a single blog is used without asking; several need a choice", () => {
  assert.equal(pickBlog([blog(1)], null)?.id, 1);
  assert.equal(pickBlog([blog(1), blog(2)], null), null);
  assert.equal(pickBlog([blog(1), blog(2)], 2)?.id, 2);
  assert.equal(pickBlog([blog(1)], 9), null);
});

test("the send-time choice wins over the blog default", () => {
  assert.equal(effectiveAction(blog(1, { default_action: "queue" }), null), "queue");
  assert.equal(effectiveAction(blog(1, { default_action: "queue" }), "publish"), "publish");
  assert.equal(effectiveAction(null, null), "draft");
});

test("the button says exactly what will happen", () => {
  assert.equal(sendButtonLabel("draft", blog(1)), "Save draft to blog-1");
  assert.equal(sendButtonLabel("queue", blog(1)), "Add to blog-1's queue");
  assert.equal(sendButtonLabel("publish", blog(1)), "Publish now on blog-1");
  assert.equal(sendButtonLabel("draft", null), "Choose a blog");
});

test("blog problems are explained plainly", () => {
  assert.equal(blogProblem(blog(1)), null);
  assert.match(blogProblem(blog(1, { supporter: false }))!, /paid supporter/);
  assert.match(blogProblem(blog(1, { paused_reason: "account_suspended" }))!, /suspended/);
});

test("drafts link to the drafts page; published posts to the post", () => {
  assert.equal(imaglrLink("draft", "https://imaglr.com/post/1"), "https://imaglr.com/drafts");
  assert.equal(imaglrLink("publish", "https://imaglr.com/post/1"), "https://imaglr.com/post/1");
});

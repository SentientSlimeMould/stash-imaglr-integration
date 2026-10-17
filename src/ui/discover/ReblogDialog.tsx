// SPDX-License-Identifier: AGPL-3.0-only
// Reblog an imaglr post to one of your blogs: choose the blog (when you have several), confirm, done. Used from
// the Discover feed, from the "From imaglr" line on Stash's image and scene pages, and from the Share editor's
// reblog composer (which adds your caption and tags). imaglr publishes a reblog straight away, so this asks first.
import React from "react";
import { runOperation } from "../api.ts";
import { ConfirmDialog } from "../ConfirmDialog.tsx";
import type { Blog } from "../model.ts";

interface Props {
  postId: string;
  creator?: string | null;
  blogs?: Blog[]; // loaded here when not given
  blogId?: number | null; // preselected
  caption?: string; // the reblog's own caption and tags (the composer)
  tags?: string[];
  onClose: () => void;
  onDone?: () => void;
}

export function ReblogDialog({ postId, creator, blogs, blogId, caption, tags, onClose, onDone }: Props) {
  const { Form } = PluginApi.libraries.Bootstrap;
  const Toast = PluginApi.hooks.useToast();
  const [list, setList] = React.useState<Blog[] | null>(blogs ?? null);
  const [chosen, setChosen] = React.useState<number | null>(blogId ?? blogs?.[0]?.id ?? null);
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => {
    if (blogs) return;
    runOperation<{ blogs: Blog[] }>("blogs_list").then((r) => {
      setList(r.blogs);
      setChosen((c) => c ?? r.blogs[0]?.id ?? null);
    }, () => setList([]));
  }, [blogs]);
  const blog = list?.find((b) => b.id === chosen);
  async function accept() {
    if (!blog) return;
    setBusy(true);
    try {
      await runOperation("reblog", { post_id: postId, blog_id: blog.id, caption: caption ?? undefined, tags: tags ?? undefined });
      Toast.success(`Reblogged to ${blog.label}.`);
      onDone?.();
      onClose();
    } catch (e) {
      Toast.error(e);
      setBusy(false);
    }
  }
  return (
    <ConfirmDialog title="Reblog" accept="Reblog" busy={busy} disabled={!blog} onAccept={accept} onCancel={onClose}>
      {list && list.length > 1 ? (
        <Form.Group>
          <Form.Label>To</Form.Label>
          <Form.Control as="select" className="text-input" value={chosen ?? ""}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setChosen(Number(e.target.value))}>
            {list.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
          </Form.Control>
        </Form.Group>
      ) : null}
      {list === null ? <p className="mb-0 text-muted">Loading your blogs…</p>
        : blog ? <p className="mb-0">Reblog {creator ? `@${creator}'s post` : "this post"} to {blog.label}? It appears on your blog straight away.</p>
        : <p className="mb-0">Add a blog in the plugin's settings first.</p>}
    </ConfirmDialog>
  );
}

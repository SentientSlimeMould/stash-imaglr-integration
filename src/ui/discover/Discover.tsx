// SPDX-License-Identifier: AGPL-3.0-only
// The Discover section of the imaglr page: your feed, your likes, and Explore (a tag, a creator, or a post from
// its link), as one column of posts you scroll through. Tapping a creator or a tag explores it; Back returns.
// Save puts a post into your Stash library (with its credit; see the backend's saving.py), Reblog shares it to
// one of your blogs. Feed and Likes stay loaded while you explore, so you come back to where you were.
import React from "react";
import { runOperation } from "../api.ts";
import { ConfirmDialog } from "../ConfirmDialog.tsx";
import type { Blog } from "../model.ts";
import { type ImaglrPost, parseSearch, SAVING, type SaveState } from "../lib/posts.ts";
import { AutoplayContext, PostCard } from "./PostCard.tsx";
import { folderReady, SaveFolderDialog, type SaveSetup } from "./SaveFolderDialog.tsx";
import { PostFeed } from "./PostFeed.tsx";

export const DISCOVER_TABS = [
  { key: "feed", title: "Feed" },
  { key: "likes", title: "Likes" },
  { key: "explore", title: "Explore" },
] as const;
export type DiscoverTab = (typeof DISCOVER_TABS)[number]["key"];


const POLL_MS = 2000;
const BLOG_KEY = "imaglr.browseBlog";

function storedBlog(): number | null {
  try {
    const v = window.localStorage.getItem(BLOG_KEY);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}

/** Saves started from this page, kept fresh while any is under way. */
function useSaves() {
  const [saves, setSaves] = React.useState<Map<string, SaveState>>(new Map());
  const busy = [...saves.values()].some((s) => SAVING.includes(s.status));
  React.useEffect(() => {
    if (!busy) return;
    const timer = window.setTimeout(() => {
      runOperation<{ saves: SaveState[] }>("save_status").then((r) => {
        setSaves((old) => {
          const fresh = new Map(old);
          for (const s of r.saves) if (fresh.has(s.post_id)) fresh.set(s.post_id, s);
          return fresh;
        });
      }, () => setSaves((old) => new Map(old))); // try again on the next tick
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [saves, busy]);
  return { saves, put: (s: SaveState) => setSaves((old) => new Map(old).set(s.post_id, s)) };
}

function ReblogDialog({ post, blogs, onClose }: { post: ImaglrPost; blogs: Blog[]; onClose: () => void }) {
  const { Form } = PluginApi.libraries.Bootstrap;
  const Toast = PluginApi.hooks.useToast();
  const [blogId, setBlogId] = React.useState<number | null>(blogs[0]?.id ?? null);
  const [busy, setBusy] = React.useState(false);
  const blog = blogs.find((b) => b.id === blogId);
  async function accept() {
    if (!blog) return;
    setBusy(true);
    try {
      await runOperation("reblog", { post_id: post.id, blog_id: blog.id });
      Toast.success(`Reblogged to ${blog.label}.`);
      onClose();
    } catch (e) {
      Toast.error(e);
      setBusy(false);
    }
  }
  return (
    <ConfirmDialog title="Reblog" accept="Reblog" busy={busy} disabled={!blog} onAccept={accept} onCancel={onClose}>
      {blogs.length > 1 ? (
        <Form.Group>
          <Form.Label>To</Form.Label>
          <Form.Control as="select" className="text-input" value={blogId ?? ""}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setBlogId(Number(e.target.value))}>
            {blogs.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
          </Form.Control>
        </Form.Group>
      ) : null}
      {blog ? <p className="mb-0">Reblog {post.creator.name ? `@${post.creator.name}'s post` : "this post"} to {blog.label}? It appears on
        your blog straight away.</p> : <p className="mb-0">Add a blog in the plugin's settings first.</p>}
    </ConfirmDialog>
  );
}

function Explore({ params, onSearch, children }: { params: URLSearchParams; onSearch: (s: string) => void; children: React.ReactNode }) {
  const { Form, Button, InputGroup } = PluginApi.libraries.Bootstrap;
  const initial = params.get("creator") ? `@${params.get("creator")}` : params.get("tag") ? `#${params.get("tag")}` : params.get("post") ?? "";
  const [text, setText] = React.useState(initial);
  React.useEffect(() => setText(initial), [initial]);
  return (
    <div className="imaglr-feed">
      <Form onSubmit={(e: React.FormEvent) => { e.preventDefault(); onSearch(text); }} className="imaglr-explore-search">
        <InputGroup>
          <Form.Control className="text-input" value={text} placeholder="#tag, @creator or a post link" enterKeyHint="search"
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setText(e.target.value)} />
          <InputGroup.Append><Button type="submit" variant="primary">Go</Button></InputGroup.Append>
        </InputGroup>
      </Form>
      {children}
    </div>
  );
}

function SinglePost({ id, ...handlers }: { id: string; saves: Map<string, SaveState>; onCreator: (n: string) => void; onTag: (t: string) => void;
  onSave: (p: ImaglrPost) => void; onReblog: (p: ImaglrPost) => void; blogId: number | null }) {
  const [post, setPost] = React.useState<ImaglrPost | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    setPost(null);
    setError(null);
    runOperation<{ post: ImaglrPost }>("post_find", { link: id, blog_id: handlers.blogId ?? undefined })
      .then((r) => setPost(r.post), (e: Error) => setError(e.message));
  }, [id, handlers.blogId]);
  if (error) return <div className="alert alert-warning">{error}</div>;
  if (!post) return <p className="text-muted">Loading…</p>;
  return <PostCard post={post} save={handlers.saves.get(post.credit_id) ?? null} onCreator={handlers.onCreator}
    onTag={handlers.onTag} onSave={handlers.onSave} onReblog={handlers.onReblog} />;
}

interface Props {
  tab: DiscoverTab;
  params: URLSearchParams;
  blogs: Blog[];
  go: (search: Record<string, string>, push?: boolean) => void;
}

export function Discover({ tab, params, blogs, go }: Props) {
  const { Form } = PluginApi.libraries.Bootstrap;
  const Toast = PluginApi.hooks.useToast();
  const [setup, setSetup] = React.useState<SaveSetup | null>(null);
  const [pendingSave, setPendingSave] = React.useState<ImaglrPost | null>(null);
  const [reblogging, setReblogging] = React.useState<ImaglrPost | null>(null);
  const [visited, setVisited] = React.useState<Set<DiscoverTab>>(new Set([tab]));
  const [blogId, setBlogId] = React.useState<number | null>(() => {
    const stored = storedBlog();
    return blogs.some((b) => b.id === stored) ? stored : (blogs.find((b) => b.ok) ?? blogs[0])?.id ?? null;
  });
  const { saves, put } = useSaves();

  React.useEffect(() => setVisited((v) => (v.has(tab) ? v : new Set(v).add(tab))), [tab]);
  React.useEffect(() => {
    runOperation<SaveSetup>("save_setup").then(setSetup, () => setSetup(null));
  }, []);

  const explore = {
    onCreator: (name: string) => name && go({ tab: "explore", creator: name }, true),
    onTag: (tag: string) => go({ tab: "explore", tag }, true),
  };

  async function startSave(post: ImaglrPost, ready = setup) {
    if (!folderReady(ready)) {
      setPendingSave(post); // first save, or the folder can't take saves: choose one, then this post saves
      return;
    }
    put({ post_id: post.credit_id, status: "queued", progress: 0, error: null, refs: [] });
    try {
      const r = await runOperation<{ save: SaveState }>("save_post", { post_id: post.id, blog_id: blogId ?? undefined });
      put(r.save);
    } catch (e) {
      put({ post_id: post.credit_id, status: "failed", progress: 0, error: (e as Error).message, refs: [] });
      Toast.error(e);
    }
  }

  const handlers = { ...explore, saves, blogId, onSave: (p: ImaglrPost) => startSave(p), onReblog: setReblogging };

  function search(text: string) {
    const found = parseSearch(text);
    if (!found) return;
    go(found.kind === "creator" ? { tab: "explore", creator: found.value } : found.kind === "tag" ? { tab: "explore", tag: found.value }
      : { tab: "explore", post: found.value }, true);
  }

  if (blogs.length === 0) {
    return <div className="alert alert-info">Add your imaglr blog in Settings to browse imaglr from here.</div>;
  }

  const creator = params.get("creator");
  const tag = params.get("tag");
  const postId = params.get("post");
  return (
    <AutoplayContext.Provider value={!!setup?.autoplay}>
    <div className="imaglr-discover">
      {blogs.length > 1 ? (
        <div className="imaglr-discover-as">
          <span className="small text-muted">Browsing as</span>
          <Form.Control as="select" size="sm" className="text-input" value={blogId ?? ""}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => {
              const id = Number(e.target.value);
              setBlogId(id);
              try { window.localStorage.setItem(BLOG_KEY, String(id)); } catch { /* private window: not remembered */ }
            }}>
            {blogs.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
          </Form.Control>
        </div>
      ) : null}
      {/* Feed and Likes stay mounted once opened, so coming back keeps your place. */}
      {visited.has("feed") ? (
        <div hidden={tab !== "feed"}><PostFeed source="feed" {...handlers} /></div>
      ) : null}
      {visited.has("likes") ? (
        <div hidden={tab !== "likes"}><PostFeed source="likes" {...handlers} /></div>
      ) : null}
      {tab === "explore" ? (
        <Explore params={params} onSearch={search}>
          {creator ? <PostFeed source="creator" name={creator} {...handlers} />
            : tag ? (<><h4 className="imaglr-explore-title">#{tag}</h4><PostFeed source="tag" tag={tag} {...handlers} /></>)
            : postId ? <SinglePost id={postId} {...handlers} />
            : <p className="text-muted">Find posts by tag, see everything a creator has posted, or paste a link to a post to save it.</p>}
        </Explore>
      ) : null}
      {pendingSave && setup ? (
        <SaveFolderDialog setup={setup} onCancel={() => setPendingSave(null)} onDone={(s) => {
          setSetup(s);
          const post = pendingSave;
          setPendingSave(null);
          if (folderReady(s)) startSave(post, s);
        }} />
      ) : null}
      {reblogging ? <ReblogDialog post={reblogging} blogs={blogs} onClose={() => setReblogging(null)} /> : null}
    </div>
    </AutoplayContext.Provider>
  );
}

// SPDX-License-Identifier: AGPL-3.0-only
// The Discover section of the imaglr page: your feed, your likes, and Explore (a tag, a creator, or a post from
// its link), as one column of posts you scroll through. Tapping a creator or a tag explores it; Back returns.
// Save puts a post into your Stash library (with its credit; see the backend's saving.py), Reblog shares it to
// one of your blogs. Feed and Likes stay loaded while you explore, so you come back to where you were.
import React from "react";
import { runOperation } from "../api.ts";
import { ConfirmDialog } from "../ConfirmDialog.tsx";
import type { Blog } from "../model.ts";
import { type ExploreOption, exploreOptions, type ImaglrPost, parseSearch, rememberSearch, SAVING, type SaveState, searchLabel } from "../lib/posts.ts";
import { AutoplayContext, Avatar, PostCard } from "./PostCard.tsx";
import { folderReady, SaveFolderDialog, type SaveSetup } from "./SaveFolderDialog.tsx";
import { ReblogDialog } from "./ReblogDialog.tsx";
import { LikesSync } from "./LikesSync.tsx";
import { ReviewDialog } from "./ReviewDialog.tsx";
import { PostFeed } from "./PostFeed.tsx";

export const DISCOVER_TABS = [
  { key: "feed", title: "Feed" },
  { key: "likes", title: "Likes" },
  { key: "explore", title: "Explore" },
] as const;
export type DiscoverTab = (typeof DISCOVER_TABS)[number]["key"];


const POLL_MS = 2000;
const BLOG_KEY = "imaglr.browseBlog";
const RECENT_KEY = "imaglr.recentSearches"; // this browser's own Explore history; nothing is sent anywhere

function storedSearches(): string[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

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

/** The Explore box: Stash's own select, typed into like a search field. Its menu offers what Enter would do,
 *  your recent searches and the creators you follow; choosing one searches. */
function Explore({ params, recent, following, onSearch, children }: { params: URLSearchParams; recent: string[];
  following: { name: string; avatar: string | null }[]; onSearch: (s: string) => void; children: React.ReactNode }) {
  const { Button } = PluginApi.libraries.Bootstrap;
  const { Icon } = PluginApi.components;
  const Select = PluginApi.libraries.ReactSelect.default;
  // What's being shown, as the select's chosen value (so the box says what you're looking at, as Stash's pickers
  // show their choice); typing starts a new search in its place.
  const current = params.get("creator") ? `@${params.get("creator")}` : params.get("tag") ? `#${params.get("tag")}`
    : params.get("post") ? `Post ${params.get("post")}` : "";
  const shown: ExploreOption | null = current ? { value: current, label: current, kind: "search" } : null;
  const [text, setText] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const go = (value: string) => {
    setText("");
    setOpen(false);
    onSearch(value);
  };
  return (
    <div className="imaglr-feed">
      <div className="imaglr-explore-search">
        <Select
          inputId="imaglr-explore"
          className="react-select imaglr-explore-select"
          classNamePrefix="react-select"
          value={shown}
          inputValue={text}
          options={exploreOptions(text, recent, following)}
          menuIsOpen={open}
          onMenuOpen={() => setOpen(true)}
          onMenuClose={() => setOpen(false)}
          onFocus={() => setOpen(true)}
          onInputChange={(v: string, meta: { action: string }) => { if (meta.action === "input-change") { setText(v); setOpen(true); } }}
          onChange={(o: ExploreOption | null) => o && go(o.value)}
          onKeyDown={(e: React.KeyboardEvent) => {
            if (e.key === "Enter" && !open && text.trim()) { e.preventDefault(); go(text); }
          }}
          filterOption={() => true}
          placeholder="#tag, @creator or a post link"
          noOptionsMessage={() => null}
          formatOptionLabel={(o: ExploreOption, meta: { context: string }) => meta.context === "value" ? o.label : (
            <span className="imaglr-explore-option">
              {o.kind === "follow" ? <Avatar url={o.avatar ?? null} name={o.label} small />
                : <Icon icon={o.kind === "recent" ? PluginApi.libraries.FontAwesomeSolid.faHistory : PluginApi.libraries.FontAwesomeSolid.faSearch} />}
              <span>{o.label}</span>
            </span>
          )}
          styles={{ menuPortal: (base: object) => ({ ...base, zIndex: 1100 }) }}
          components={{ IndicatorSeparator: () => null, DropdownIndicator: () => null }}
          menuPortalTarget={document.body}
        />
        <Button variant="primary" onClick={() => (text.trim() ? go(text) : shown ? onSearch(shown.value) : undefined)}>Go</Button>
      </div>
      {children}
    </div>
  );
}

function SinglePost({ id, ...handlers }: { id: string; saves: Map<string, SaveState>; onCreator: (n: string) => void; onTag: (t: string) => void;
  onSave: (p: ImaglrPost) => void; onReblog: (p: ImaglrPost) => void; blogId: number | null;
  onLike: (p: ImaglrPost) => Promise<{ liked: boolean | null; likes: number | null }> }) {
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
    onTag={handlers.onTag} onSave={handlers.onSave} onReblog={handlers.onReblog} onLike={handlers.onLike} />;
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
  const [reviewing, setReviewing] = React.useState<ImaglrPost | null>(null);
  const [afterFolder, setAfterFolder] = React.useState<(() => void) | null>(null); // the sync waiting for a save folder
  const [likesKey, setLikesKey] = React.useState(0); // bumped after a sync, so the Likes list shows what's saved
  const [visited, setVisited] = React.useState<Set<DiscoverTab>>(new Set([tab]));
  const [blogId, setBlogId] = React.useState<number | null>(() => {
    const stored = storedBlog();
    return blogs.some((b) => b.id === stored) ? stored : (blogs.find((b) => b.ok) ?? blogs[0])?.id ?? null;
  });
  const { saves, put } = useSaves();
  const [recent, setRecent] = React.useState<string[]>(storedSearches);
  const [following, setFollowing] = React.useState<{ name: string; avatar: string | null }[]>([]);

  React.useEffect(() => setVisited((v) => (v.has(tab) ? v : new Set(v).add(tab))), [tab]);
  React.useEffect(() => {
    runOperation<SaveSetup>("save_setup").then(setSetup, () => setSetup(null));
  }, []);
  // The creators the browsing blog follows, for Explore's suggestions (only once Explore is opened).
  React.useEffect(() => {
    if (tab !== "explore" || !blogId) return;
    runOperation<{ people: { name: string; avatar: string | null }[] }>("following", { blog_id: blogId })
      .then((r) => setFollowing(r.people), () => setFollowing([]));
  }, [tab === "explore", blogId]);

  const explore = {
    onCreator: (name: string) => name && go({ tab: "explore", creator: name }, true),
    onTag: (tag: string) => go({ tab: "explore", tag }, true),
  };

  async function startSave(post: ImaglrPost, ready = setup) {
    if (!ready || !folderReady(ready)) {
      setPendingSave(post); // first save, or the folder can't take saves: choose one, then this post saves
      return;
    }
    if (!ready.quick_save) {
      setReviewing(post); // the review saves it (or not)
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

  async function like(post: ImaglrPost) {
    try {
      return await runOperation<{ liked: boolean | null; likes: number | null }>("like", { post_id: post.id, blog_id: blogId ?? undefined });
    } catch (e) {
      Toast.error(e);
      throw e;
    }
  }

  const handlers = { ...explore, saves, blogId, onSave: (p: ImaglrPost) => startSave(p), onReblog: setReblogging, onLike: like };

  function search(text: string) {
    const found = parseSearch(text);
    if (!found) return;
    const next = rememberSearch(recent, searchLabel(found, text));
    setRecent(next);
    try { window.localStorage.setItem(RECENT_KEY, JSON.stringify(next)); } catch { /* private window: not remembered */ }
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
        <div hidden={tab !== "likes"}>
          <LikesSync blogId={blogId} ready={folderReady(setup)} onNeedFolder={(then) => setAfterFolder(() => then)}
            onFinished={() => setLikesKey((k) => k + 1)} />
          <PostFeed key={likesKey} source="likes" {...handlers} />
        </div>
      ) : null}
      {tab === "explore" ? (
        <Explore params={params} recent={recent} following={following} onSearch={search}>
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
      {afterFolder && setup ? (
        <SaveFolderDialog setup={setup} onCancel={() => setAfterFolder(null)} onDone={(s) => {
          setSetup(s);
          const then = afterFolder;
          setAfterFolder(null);
          if (folderReady(s)) then();
        }} />
      ) : null}
      {reblogging ? <ReblogDialog postId={reblogging.id} creator={reblogging.creator.name} blogs={blogs} onClose={() => setReblogging(null)} /> : null}
      {reviewing ? (
        <ReviewDialog post={reviewing} blogId={blogId} onCancel={() => setReviewing(null)}
          onDone={(s) => { put(s); setReviewing(null); }} />
      ) : null}
    </div>
    </AutoplayContext.Provider>
  );
}

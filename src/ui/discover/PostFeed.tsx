// SPDX-License-Identifier: AGPL-3.0-only
// A list of imaglr posts that keeps going as you scroll: the feed, your likes, a tag or a creator. The next page
// is asked for well before the end, so scrolling doesn't stop. A creator's list opens with their profile.
import React from "react";
import { runOperation } from "../api.ts";
import type { BrowsePage, BrowseSource, CreatorProfile, ImaglrPost, SaveState } from "../lib/posts.ts";
import { shortCount } from "../lib/posts.ts";
import { Avatar, PostCard } from "./PostCard.tsx";

interface Props {
  source: BrowseSource;
  tag?: string;
  name?: string;
  blogId: number | null;
  saves: Map<string, SaveState>;
  onCreator: (name: string) => void;
  onTag: (tag: string) => void;
  onSave: (post: ImaglrPost) => void;
  onReblog: (post: ImaglrPost) => void;
  onLike: (post: ImaglrPost) => Promise<{ liked: boolean | null; likes: number | null }>;
}

function CreatorHeader({ profile }: { profile: CreatorProfile }) {
  const { Icon } = PluginApi.components;
  const fa = PluginApi.libraries.FontAwesomeSolid;
  return (
    <div className="card imaglr-creator">
      <div className="card-body">
        <div className="imaglr-creator-head">
          <Avatar url={profile.avatar} name={profile.name} large />
          <div>
            <h4 className="mb-1">{profile.name}</h4>
            <div className="small text-muted">
              {shortCount(profile.counts.posts)} posts · {shortCount(profile.counts.followers)} followers
            </div>
          </div>
          {profile.url ? (
            <a className="btn btn-secondary ml-auto" href={profile.url} target="_blank" rel="noopener noreferrer">
              <Icon icon={fa.faExternalLinkAlt} /> imaglr
            </a>
          ) : null}
        </div>
        {profile.description ? <p className="imaglr-creator-bio mt-2 mb-0">{profile.description}</p> : null}
      </div>
    </div>
  );
}

export function PostFeed({ source, tag, name, blogId, saves, onCreator, onTag, onSave, onReblog, onLike }: Props) {
  const { Button } = PluginApi.libraries.Bootstrap;
  const { LoadingIndicator } = PluginApi.components;
  const [posts, setPosts] = React.useState<ImaglrPost[]>([]);
  const [next, setNext] = React.useState<string | null>(null);
  const [profile, setProfile] = React.useState<CreatorProfile | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [ended, setEnded] = React.useState(false);
  const sentinel = React.useRef<HTMLDivElement>(null);
  const busy = React.useRef(false);
  const key = `${source}|${tag ?? ""}|${name ?? ""}|${blogId ?? ""}`;
  const current = React.useRef(key);

  const load = React.useCallback(async (link: string | null) => {
    if (busy.current) return;
    busy.current = true;
    setLoading(true);
    const asked = key;
    try {
      const page = await runOperation<BrowsePage>("browse", { source, tag, name, next: link, blog_id: blogId ?? undefined });
      if (current.current !== asked) return; // the list changed while this page was on its way
      setPosts((old) => {
        const seen = new Set(old.map((p) => p.id));
        return [...(link ? old : []), ...page.posts.filter((p) => !link || !seen.has(p.id))];
      });
      if (!link) setProfile(page.profile);
      setNext(page.next);
      setEnded(!page.next);
      setError(null);
    } catch (e) {
      if (current.current === asked) setError((e as Error).message);
    } finally {
      busy.current = false;
      setLoading(false);
    }
  }, [key]);

  React.useEffect(() => {
    current.current = key;
    setPosts([]);
    setNext(null);
    setProfile(null);
    setEnded(false);
    setError(null);
    busy.current = false;
    load(null);
  }, [key]);

  // The next page is fetched while the last screenful is still being read.
  React.useEffect(() => {
    const el = sentinel.current;
    if (!el || !next || error || typeof IntersectionObserver === "undefined") return;
    const watch = new IntersectionObserver(([e]) => e.isIntersecting && load(next), { rootMargin: "150% 0px" });
    watch.observe(el);
    return () => watch.disconnect();
  }, [next, error, load]);

  return (
    <div className="imaglr-feed">
      {profile ? <CreatorHeader profile={profile} /> : null}
      {posts.map((p) => (
        <PostCard key={p.id} post={p} save={saves.get(p.credit_id) ?? null} onCreator={onCreator} onTag={onTag}
          onSave={onSave} onReblog={onReblog} onLike={onLike} />
      ))}
      <div ref={sentinel} />
      {loading ? (LoadingIndicator ? <LoadingIndicator small /> : <p className="text-muted">Loading…</p>) : null}
      {error ? (
        <div className="alert alert-warning imaglr-feed-end">
          {error} <Button variant="secondary" size="sm" onClick={() => load(posts.length ? next : null)}>Try again</Button>
        </div>
      ) : null}
      {ended && !loading && !error ? (
        <p className="text-muted text-center imaglr-feed-end">{posts.length ? "That's everything for now." : "Nothing here yet."}</p>
      ) : null}
    </div>
  );
}

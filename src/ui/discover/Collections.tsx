// SPDX-License-Identifier: AGPL-3.0-only
// The Collections tab: your imaglr bookmarks, grouped as you grouped them on imaglr. It opens on your collections
// as Stash's own cards, All saved first; tapping one scrolls its posts with the usual Save, Reblog and Like.
// Reading only: the plugin never changes your bookmarks on imaglr.
import React from "react";
import { runOperation } from "../api.ts";
import type { CollectionsList } from "../lib/posts.ts";
import { CardGrid, type GridItem } from "../queue/CardGrid.tsx";
import { ROUTE } from "../routes.ts";
import { pictureSrc } from "./PostCard.tsx";
import { PostFeed } from "./PostFeed.tsx";

type FeedProps = Omit<React.ComponentProps<typeof PostFeed>, "source" | "collection">;

// The last list per blog, shown at once when you come back while a fresh one loads.
const remembered = new Map<number, CollectionsList>();

const postCount = (n: number) => `${n} ${n === 1 ? "post" : "posts"}`;
const collectionUrl = (id: string) => `${ROUTE}?tab=collections&collection=${encodeURIComponent(id)}`;

export function Collections({ open, feed }: { open: string | null; feed: FeedProps }) {
  const { Button } = PluginApi.libraries.Bootstrap;
  const { Link } = PluginApi.libraries.ReactRouterDOM;
  const { Icon, LoadingIndicator } = PluginApi.components;
  const fa = PluginApi.libraries.FontAwesomeSolid;
  const blogId = feed.blogId;
  const [list, setList] = React.useState<CollectionsList | null>(() => (blogId ? remembered.get(blogId) ?? null : null));
  const [error, setError] = React.useState<string | null>(null);
  const [attempt, setAttempt] = React.useState(0);
  const [covers, setCovers] = React.useState<Map<string, string>>(new Map()); // imaglr address -> what the page loads

  React.useEffect(() => {
    if (!blogId) return;
    let current = true;
    setList(remembered.get(blogId) ?? null);
    setError(null);
    runOperation<CollectionsList>("collections", { blog_id: blogId }).then((r) => {
      if (!current) return;
      remembered.set(blogId, r);
      setList(r);
    }, (e) => current && setError((e as Error).message));
    return () => { current = false; };
  }, [blogId, attempt]);
  React.useEffect(() => {
    const wanted = [list?.cover, ...(list?.collections.map((c) => c.cover) ?? [])].filter((u): u is string => !!u && !covers.has(u));
    for (const url of new Set(wanted)) {
      pictureSrc(url).then((src) => setCovers((m) => new Map(m).set(url, src)), () => undefined);
    }
  }, [list]);
  const cover = (url: string | null) => (url ? covers.get(url) ?? null : null);

  if (open) {
    const shown = open === "all" ? (list ? { name: "All saved", count: list.total } : null)
      : list?.collections.find((c) => c.id === open) ?? null;
    return (
      <>
        <div className="imaglr-collection-head">
          {/* replace, not push: Back from the list then leaves Collections rather than reopening this one */}
          <Link to={`${ROUTE}?tab=collections`} replace className="btn btn-secondary btn-sm">
            <Icon icon={fa.faChevronLeft} /> Collections
          </Link>
          {shown ? <h4 className="mb-0">{shown.name}</h4> : null}
          {shown ? <span className="text-muted">{postCount(shown.count)}</span> : null}
        </div>
        <PostFeed source="saved" collection={open} {...feed} />
      </>
    );
  }

  if (!list) {
    return error ? (
      <div className="alert alert-warning">
        {error} <Button variant="secondary" size="sm" onClick={() => setAttempt((a) => a + 1)}>Try again</Button>
      </div>
    ) : LoadingIndicator ? <LoadingIndicator small /> : <p className="text-muted">Loading…</p>;
  }
  if (!list.total && !list.collections.length) {
    return (
      <p className="text-muted imaglr-empty">
        Nothing bookmarked on imaglr yet. Posts you save on imaglr, and the collections you sort them into, show up here.
      </p>
    );
  }
  const items: GridItem[] = [
    { id: "all", title: "All saved", url: collectionUrl("all"), thumb: cover(list.cover), detail: postCount(list.total) },
    ...list.collections.map((c) => ({ id: c.id, title: c.name, url: collectionUrl(c.id), thumb: cover(c.cover), detail: postCount(c.count) })),
  ];
  return <CardGrid items={items} view="grid" zoom={1} />;
}

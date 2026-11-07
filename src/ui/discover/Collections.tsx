// SPDX-License-Identifier: AGPL-3.0-only
// The Collections tab: your imaglr bookmarks, grouped as you grouped them on imaglr. It opens on your collections
// as Stash's own cards, All saved first; tapping one scrolls its posts with the usual Save, Reblog and Like, and
// Import to library brings the collection into Stash: what's missing is saved, and every post of it in your
// library gets the collection's tag, under Imaglr Collections. Reading only: the plugin never changes your
// bookmarks on imaglr.
import React from "react";
import { runOperation } from "../api.ts";
import { ConfirmDialog } from "../ConfirmDialog.tsx";
import { type CollectionsList, libraryCount, type SyncState } from "../lib/posts.ts";
import { CardGrid, type GridItem } from "../queue/CardGrid.tsx";
import { ROUTE } from "../routes.ts";
import { SyncProgress, useLibrarySync } from "./LikesSync.tsx";
import { pictureSrc } from "./PostCard.tsx";
import { PostFeed } from "./PostFeed.tsx";

type FeedProps = Omit<React.ComponentProps<typeof PostFeed>, "source" | "collection">;

// The last list per blog, shown at once when you come back while a fresh one loads.
const remembered = new Map<number, CollectionsList>();

const postCount = (n: number) => `${n} ${n === 1 ? "post" : "posts"}`;
const collectionUrl = (id: string) => `${ROUTE}?tab=collections&collection=${encodeURIComponent(id)}`;

/** Import to library for one collection (or "all"): how much is there already, the button, then progress. */
function CollectionImport({ id, name, blogId, ready, onNeedFolder, onImported }: {
  id: string;
  name: string;
  blogId: number | null;
  ready: boolean; // the save folder can take saves
  onNeedFolder: (then: () => void) => void;
  onImported: () => void;
}) {
  const { Button } = PluginApi.libraries.Bootstrap;
  const { Icon } = PluginApi.components;
  const Toast = PluginApi.hooks.useToast();
  const mine = (s: SyncState) => s.source === "collection" && s.collection_id === id;
  const [count, setCount] = React.useState<{ savable: number | null; in_library: number | null } | null>(null);
  const [counted, setCounted] = React.useState(0); // bumped after an import, to count again
  const { sync, start, stop } = useLibrarySync(mine, () => { setCounted((n) => n + 1); onImported(); });
  const [asking, setAsking] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    let current = true;
    setCount(null);
    runOperation<{ savable: number | null; in_library: number | null }>("collection_status", { collection: id, blog_id: blogId ?? undefined })
      .then((r) => current && setCount(r), () => undefined);
    return () => { current = false; };
  }, [id, blogId, counted]);

  async function begin() {
    setBusy(true);
    try {
      await start("import_collection", { collection: id, blog_id: blogId ?? undefined });
      setAsking(false);
    } catch (e) {
      Toast.error(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="imaglr-sync">
      {sync.running ? <SyncProgress sync={sync} mine={mine(sync)} onStop={stop} /> : (
        <>
          <Button variant="primary" onClick={() => (ready ? setAsking(true) : onNeedFolder(() => setAsking(true)))}>
            <Icon icon={PluginApi.libraries.FontAwesomeSolid.faDownload} /> Import to library
          </Button>
          {count ? <span className="small text-muted">{libraryCount(count.savable, count.in_library)}</span> : null}
        </>
      )}
      {asking ? (
        <ConfirmDialog title={`Import ${name}`} accept="Import" busy={busy} onAccept={begin} onCancel={() => setAsking(false)}>
          <p>Saves every post in {id === "all" ? "your bookmarks" : "this collection"} that isn't in your library yet,
            each with its credit, using your import rules and exact name matches (there's no review for each post).</p>
          {id === "all" ? null : (
            <p>Every post of the collection in your library, new or saved before, is tagged <strong>{name}</strong>,
              under <strong>Imaglr Collections</strong>.</p>
          )}
          <p className="mb-0">It runs as a Stash task; you can stop it here. Import again any time to bring it up to date.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

export function Collections({ open, feed, ready, onNeedFolder }: {
  open: string | null;
  feed: FeedProps;
  ready: boolean;
  onNeedFolder: (then: () => void) => void;
}) {
  const { Button } = PluginApi.libraries.Bootstrap;
  const { Link } = PluginApi.libraries.ReactRouterDOM;
  const { Icon, LoadingIndicator } = PluginApi.components;
  const fa = PluginApi.libraries.FontAwesomeSolid;
  const blogId = feed.blogId;
  const [list, setList] = React.useState<CollectionsList | null>(() => (blogId ? remembered.get(blogId) ?? null : null));
  const [error, setError] = React.useState<string | null>(null);
  const [attempt, setAttempt] = React.useState(0);
  const [covers, setCovers] = React.useState<Map<string, string>>(new Map()); // imaglr address -> what the page loads
  const [imported, setImported] = React.useState(0); // bumped after an import, so the posts show what's saved

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
        {shown ? (
          <CollectionImport id={open} name={shown.name} blogId={blogId} ready={ready} onNeedFolder={onNeedFolder}
            onImported={() => setImported((n) => n + 1)} />
        ) : null}
        <PostFeed key={imported} source="saved" collection={open} {...feed} />
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

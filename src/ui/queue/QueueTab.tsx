// SPDX-License-Identifier: AGPL-3.0-only
// The Clips and Images tabs: what's waiting to be sent, one card per item or post. Tap a card to edit and send.
import React from "react";
import { runOperation } from "../api.ts";
import { Editor } from "../editor/Editor.tsx";
import type { QueueResponse } from "../model.ts";
import { ItemCard } from "./ItemCard.tsx";

const POLL_MS = 2000;

const EMPTY = {
  clips: (tag: string) => (
    <>
      <p>No clips waiting.</p>
      <p>
        Open a scene in Stash and use its <strong>imaglr</strong> tab to make a clip, or tag any scene marker{" "}
        <strong>{tag}</strong>.
      </p>
    </>
  ),
  images: (tag: string) => (
    <>
      <p>No images waiting.</p>
      <p>
        In Stash, tag images <strong>{tag}</strong>, or tick images in any image list and choose{" "}
        <strong>⋯ → Add to imaglr</strong>. Stills saved from clips appear here too.
      </p>
    </>
  ),
};

export function QueueTab({ tab, openId }: { tab: "clips" | "images"; openId: string | null }) {
  const { Button } = PluginApi.libraries.Bootstrap;
  const { LoadingIndicator } = PluginApi.components;
  const [data, setData] = React.useState<QueueResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [editing, setEditing] = React.useState<string | null>(openId);

  const load = React.useCallback(() => {
    setLoading(true);
    return runOperation<QueueResponse>("queue")
      .then((d) => {
        setData(d);
        setError(null);
      }, (e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Sends interrupted by a Stash restart are marked failed before the first load.
  React.useEffect(() => {
    runOperation("recover").catch(() => undefined).finally(load);
  }, [load]);

  // While anything is being sent, keep the cards' progress fresh.
  const items = data?.items.filter((c) => c.tab === tab) ?? [];
  const inFlight = items.some((c) => c.status === "exporting" || c.status === "sending");
  React.useEffect(() => {
    if (!inFlight || editing) return;
    const timer = window.setTimeout(load, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [data, inFlight, editing, load]);

  if (error) {
    return (
      <div className="alert alert-danger">
        Couldn't load the queue: {error}{" "}
        <Button variant="link" className="p-0" onClick={load}>Try again</Button>
      </div>
    );
  }
  if (!data) return LoadingIndicator ? <LoadingIndicator /> : <p className="text-muted">Loading…</p>;

  return (
    <>
      <div className="imaglr-toolbar">
        <span className="text-muted">
          {items.length} {items.length === 1 ? "item" : "items"}
        </span>
        <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </Button>
      </div>
      {items.length === 0 ? (
        <div className="imaglr-empty text-muted">{EMPTY[tab](data.tags.queue.name)}</div>
      ) : (
        <div className="imaglr-grid">
          {items.map((card) => (
            <button key={card.id} type="button" className="imaglr-card-button" onClick={() => setEditing(card.id)}>
              <ItemCard card={card} highlighted={card.id === openId} />
            </button>
          ))}
        </div>
      )}
      {editing ? (
        <Editor
          itemId={editing}
          onClose={(changed) => {
            setEditing(null);
            if (changed) load();
          }}
        />
      ) : null}
    </>
  );
}

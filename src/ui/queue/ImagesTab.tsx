// SPDX-License-Identifier: AGPL-3.0-only
// The Images tab: queued Stash images and multi-image posts. Tap a card to edit and send it.
import React from "react";
import { runOperation } from "../api.ts";
import { Editor } from "../editor/Editor.tsx";
import type { QueueResponse } from "../model.ts";
import { ItemCard } from "./ItemCard.tsx";

const POLL_MS = 2000;

export function ImagesTab({ openId }: { openId: string | null }) {
  const { Button } = PluginApi.libraries.Bootstrap;
  const { LoadingIndicator } = PluginApi.components;
  const [data, setData] = React.useState<QueueResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [editing, setEditing] = React.useState<string | null>(openId);

  const load = React.useCallback(() => {
    setLoading(true);
    return runOperation<QueueResponse>("images_queue")
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
  const inFlight = data?.items.some((c) => c.status === "exporting" || c.status === "sending");
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
          {data.items.length} {data.items.length === 1 ? "item" : "items"}
        </span>
        <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </Button>
      </div>
      {data.items.length === 0 ? (
        <div className="imaglr-empty text-muted">
          <p>No images waiting.</p>
          <p>
            In Stash, tag images <strong>{data.tags.queue.name}</strong>, or tick images in any image list and
            choose <strong>⋯ → Add to imaglr</strong>.
          </p>
        </div>
      ) : (
        <div className="imaglr-grid">
          {data.items.map((card) => (
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

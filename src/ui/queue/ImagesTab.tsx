// SPDX-License-Identifier: AGPL-3.0-only
// The Images tab: queued Stash images and multi-image posts.
import React from "react";
import { runOperation } from "../api.ts";
import type { QueueResponse } from "../model.ts";
import { ItemCard } from "./ItemCard.tsx";

export function ImagesTab({ openId }: { openId: string | null }) {
  const { Button } = PluginApi.libraries.Bootstrap;
  const { LoadingIndicator } = PluginApi.components;
  const [data, setData] = React.useState<QueueResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  const load = React.useCallback(() => {
    setLoading(true);
    runOperation<QueueResponse>("images_queue")
      .then((d) => {
        setData(d);
        setError(null);
      }, (e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  React.useEffect(load, [load]);

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
            <ItemCard key={card.id} card={card} highlighted={card.id === openId} />
          ))}
        </div>
      )}
    </>
  );
}

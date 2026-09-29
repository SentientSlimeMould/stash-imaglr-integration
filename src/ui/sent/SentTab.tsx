// SPDX-License-Identifier: AGPL-3.0-only
// The Sent tab: what went where, tags imaglr dropped, and a retry when queueing/publishing failed.
import React from "react";
import { baseUrl, runOperation } from "../api.ts";
import { fmtDate } from "../lib/format.ts";
import { imaglrLink, SENT_AS_LABELS } from "../lib/send.ts";
import type { SentItem } from "../model.ts";

export function SentTab() {
  const { Button, Badge } = PluginApi.libraries.Bootstrap;
  const { LoadingIndicator } = PluginApi.components;
  const Toast = PluginApi.hooks.useToast();
  const [items, setItems] = React.useState<SentItem[] | null>(null);

  const load = React.useCallback(() => {
    runOperation<{ items: SentItem[] }>("sent_list").then((r) => setItems(r.items), (e: Error) => Toast.error(e));
  }, []);
  React.useEffect(load, [load]);

  async function retry(item: SentItem) {
    try {
      await runOperation("retry_follow_up", { item_id: item.id });
      Toast.success("Done.");
      load();
    } catch (e) {
      Toast.error(e);
    }
  }

  async function alwaysDrop(tag: string) {
    try {
      await runOperation("tag_rule_set", { stash_tag: tag, imaglr_tags: [] });
      Toast.success(`"${tag}" won't be suggested again.`);
    } catch (e) {
      Toast.error(e);
    }
  }

  if (!items) return LoadingIndicator ? <LoadingIndicator /> : <p className="text-muted">Loading…</p>;
  if (!items.length) return <p className="text-muted imaglr-empty">Nothing sent yet.</p>;

  return (
    <ul className="imaglr-sent">
      {items.map((item) => (
        <li key={item.id} className="imaglr-sent-row card">
          <div className="imaglr-sent-thumb">
            {item.thumb ? <img src={baseUrl() + item.thumb} alt="" loading="lazy" /> : null}
          </div>
          <div className="imaglr-sent-body">
            <div className="imaglr-card-title">
              {item.title}
              {item.files > 1 ? <span className="text-muted"> + {item.files - 1} more</span> : null}
            </div>
            <div className="small">
              <Badge variant={item.sent_as === "publish" ? "success" : "primary"}>{SENT_AS_LABELS[item.sent_as]}</Badge>{" "}
              {item.blog ? `on ${item.blog}` : null} · {fmtDate(item.sent_at)} ·{" "}
              <a href={imaglrLink(item.sent_as, item.post_url)} target="_blank" rel="noreferrer">
                {item.sent_as === "draft" ? "Open imaglr drafts" : "Open on imaglr"}
              </a>
            </div>
            {item.followup_failed ? (
              <div className="small text-warning">
                {item.error_detail}{" "}
                <Button variant="link" size="sm" className="p-0" onClick={() => retry(item)}>
                  {item.action === "publish" ? "Retry publishing" : "Retry adding to queue"}
                </Button>
              </div>
            ) : item.error_detail ? (
              <div className="small text-warning">{item.error_detail}</div>
            ) : null}
            {item.dropped_tags.length ? (
              <div className="small">
                <span className="text-muted">imaglr dropped:</span>{" "}
                {item.dropped_tags.map((tag) => (
                  <span key={tag} className="imaglr-dropped">
                    {tag}{" "}
                    <Button variant="link" size="sm" className="p-0" onClick={() => alwaysDrop(tag)}>Always drop</Button>
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}

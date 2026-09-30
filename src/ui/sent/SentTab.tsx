// SPDX-License-Identifier: AGPL-3.0-only
// The Sent tab: what went where, tags imaglr dropped, and a retry when queueing/publishing failed.
// Paged on the backend (history grows without limit), with Stash's paging controls.
import React from "react";
import { baseUrl, runOperation } from "../api.ts";
import { fmtDate } from "../lib/format.ts";
import { imaglrLink, SENT_AS_LABELS } from "../lib/send.ts";
import { loadControls, saveControls } from "../lib/sort.ts";
import type { SentItem } from "../model.ts";
import { Pager, PageSizeSelect } from "../queue/Paging.tsx";

interface SentPage {
  items: SentItem[];
  total: number;
  page: number;
  per_page: number;
}

export function SentTab() {
  const { Button, Badge, ButtonToolbar } = PluginApi.libraries.Bootstrap;
  const { LoadingIndicator } = PluginApi.components;
  const Toast = PluginApi.hooks.useToast();
  PluginApi.hooks.useLoadComponents([PluginApi.loadableComponents.Images]); // Stash's Pagination
  const [perPage, setPerPage] = React.useState(() => loadControls("sent").perPage);
  const [page, setPage] = React.useState(1);
  const [data, setData] = React.useState<SentPage | null>(null);

  const load = React.useCallback(() => {
    runOperation<SentPage>("sent_list", { page, per_page: perPage }).then((r) => {
      setData(r);
      if (r.page !== page) setPage(r.page);
    }, (e: Error) => Toast.error(e));
  }, [page, perPage]);
  React.useEffect(load, [load]);

  function changePerPage(size: number) {
    setPerPage(size);
    saveControls("sent", { ...loadControls("sent"), perPage: size });
    setPage(1);
  }

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

  if (!data) return LoadingIndicator ? <LoadingIndicator /> : <p className="text-muted">Loading…</p>;

  return (
    <>
      <ButtonToolbar className="filtered-list-toolbar">
        <PageSizeSelect value={perPage} onChange={changePerPage} />
        <Button variant="secondary" onClick={load}>Refresh</Button>
      </ButtonToolbar>
      {data.total === 0 ? <p className="text-muted imaglr-empty">Nothing sent yet.</p> : null}
      <ul className="imaglr-sent">
        {data.items.map((item) => (
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
      <Pager page={data.page} perPage={perPage} total={data.total} onChange={(p) => { setPage(p); window.scrollTo({ top: 0 }); }} />
    </>
  );
}

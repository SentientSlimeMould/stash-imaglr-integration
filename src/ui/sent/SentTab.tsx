// SPDX-License-Identifier: AGPL-3.0-only
// The Sent tab: what went where, shown exactly like the Clips and Images tabs (Stash's list toolbar,
// cards, paging). History grows without limit, so searching, filtering, sorting and paging happen on
// the backend. A card opens its details (?open=<id>).
import React from "react";
import { runOperation } from "../api.ts";
import { fmtDate } from "../lib/format.ts";
import { SENT_AS_LABELS } from "../lib/send.ts";
import { loadControls, saveControls, type QueueControlsState } from "../lib/sort.ts";
import type { SentItem } from "../model.ts";
import { CardGrid, type GridItem } from "../queue/CardGrid.tsx";
import { Pager } from "../queue/Paging.tsx";
import { ROUTE } from "../routes.ts";
import { Toolbar } from "../queue/Toolbar.tsx";
import { SentDialog } from "./SentDialog.tsx";

interface SentPage {
  items: SentItem[];
  total: number;
  page: number;
  per_page: number;
  blogs: { id: number; name: string }[];
}

function cardDetail(item: SentItem): string {
  const when = fmtDate(item.sent_at);
  return item.blog ? `${item.blog} · ${when}` : when;
}

export function SentTab({ openId }: { openId: string | null }) {
  const { Button } = PluginApi.libraries.Bootstrap;
  const { useHistory } = PluginApi.libraries.ReactRouterDOM;
  const { LoadingIndicator } = PluginApi.components;
  const history = useHistory();
  const [controls, setControls] = React.useState<QueueControlsState>(() => loadControls("sent"));
  const [page, setPage] = React.useState(1);
  const [data, setData] = React.useState<SentPage | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(() => {
    return runOperation<SentPage>("sent_list", {
      page, per_page: controls.perPage, q: controls.search, sort: controls.sort, dir: controls.dir,
      blog_id: controls.blog, sent_as: controls.sentAs === "all" ? null : controls.sentAs,
    }).then((r) => {
      setData(r);
      setError(null);
      if (r.page !== page) setPage(r.page); // the list shrank under us
    }, (e: Error) => setError(e.message));
  }, [page, controls.perPage, controls.search, controls.sort, controls.dir, controls.blog, controls.sentAs]);
  React.useEffect(() => { void load(); }, [load]);

  function updateControls(next: QueueControlsState) {
    setControls(next);
    saveControls("sent", next);
    setPage(1);
  }

  const filtered = !!controls.search || controls.blog != null || controls.sentAs !== "all";

  let body: React.ReactNode;
  if (error) {
    body = (
      <div className="alert alert-danger">
        Couldn't load the sent posts: {error}{" "}
        <Button variant="link" className="p-0" onClick={() => void load()}>Try again</Button>
      </div>
    );
  } else if (!data) {
    body = LoadingIndicator ? <LoadingIndicator /> : <p className="text-muted">Loading…</p>;
  } else if (data.total === 0) {
    body = <p className="text-muted imaglr-empty">{filtered ? "Nothing matches these filters." : "Nothing sent yet."}</p>;
  } else {
    const gridItems: GridItem[] = data.items.map((item) => ({
      id: item.id,
      title: item.title,
      url: `${ROUTE}?tab=sent&open=${item.id}`,
      thumb: item.thumb,
      detail: cardDetail(item),
      badge: item.followup_failed
        ? { text: item.action === "publish" ? "Publish failed" : "Queue failed", variant: "danger" }
        : { text: SENT_AS_LABELS[item.sent_as], variant: item.sent_as === "publish" ? "success" : "primary" },
      count: item.files.length > 1 ? item.files.length : undefined,
    }));
    body = <CardGrid items={gridItems} view={controls.view} zoom={controls.zoom} highlightId={openId} />;
  }

  return (
    <div>
      <Toolbar
        tab="sent"
        controls={controls}
        items={[]}
        blogs={data?.blogs}
        selected={0}
        selectionActions={[]}
        onChange={updateControls}
        onRefresh={() => void load()}
      />
      {body}
      {data && data.total > 0 ? (
        <Pager page={data.page} perPage={controls.perPage} total={data.total}
          onChange={(p) => { setPage(p); window.scrollTo({ top: 0 }); }} />
      ) : null}
      {openId ? (
        <SentDialog
          itemId={openId}
          onClose={(changed) => {
            history.replace({ search: "?tab=sent" });
            if (changed) void load();
          }}
        />
      ) : null}
    </div>
  );
}

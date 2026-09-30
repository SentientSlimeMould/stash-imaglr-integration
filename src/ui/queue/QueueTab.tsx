// SPDX-License-Identifier: AGPL-3.0-only
// The Clips and Images tabs: what's waiting to be sent, shown with Stash's own list toolbar and cards.
// A card links to its editor (?open=<id>), so tapping opens it and it can also be opened in a new tab.
import React from "react";
import { runOperation } from "../api.ts";
import { Editor } from "../editor/Editor.tsx";
import { applyControls, cardWidth, loadControls, paginate, saveControls, type QueueControlsState } from "../lib/sort.ts";
import { MAX_POST_FILES } from "../lib/imageActions.ts";
import { STATUS_LABELS, STATUS_VARIANTS, type Card, type QueueResponse } from "../model.ts";
import { ROUTE } from "../routes.ts";
import { CardImage, cardDetail, CardOverlays, FallbackCard } from "./ItemCard.tsx";
import { Pager } from "./Paging.tsx";
import { SendAllDialog } from "./SendAllDialog.tsx";
import { Toolbar, type SelectionAction } from "./Toolbar.tsx";

const BUSY = ["exporting", "sending"];

const EMPTY = {
  clips: (tag: string) => (
    <>
      <p>No clips waiting.</p>
      <p>
        In Stash, add the tag <strong>{tag}</strong> to a scene marker (on the scene's <strong>Markers</strong> tab).
        Its start and end become the clip; you can trim it here.
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

function useContainerWidth(ref: React.RefObject<HTMLDivElement>) {
  const [width, setWidth] = React.useState(0);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

export interface QueueProps {
  data: QueueResponse | null;
  error: string | null;
  load: () => Promise<unknown>;
}

export function QueueTab({ tab, openId, data, error, load }: { tab: "clips" | "images"; openId: string | null } & QueueProps) {
  const { Button, Table, Badge } = PluginApi.libraries.Bootstrap;
  const { Link, useHistory } = PluginApi.libraries.ReactRouterDOM;
  const { LoadingIndicator } = PluginApi.components;
  const Toast = PluginApi.hooks.useToast();
  const history = useHistory();
  // Stash's GridCard and Pagination are loaded on demand; these modules bring them in.
  const loading = PluginApi.hooks.useLoadComponents([PluginApi.loadableComponents.SceneCard, PluginApi.loadableComponents.Images]);
  const GridCard = loading ? null : PluginApi.components.GridCard;

  const [controls, setControls] = React.useState<QueueControlsState>(() => loadControls(tab));
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [sendAll, setSendAll] = React.useState<string[] | null>(null);
  const [page, setPage] = React.useState(1);
  const box = React.useRef<HTMLDivElement>(null);
  const width = useContainerWidth(box);
  const isMobile = typeof window !== "undefined" && window.matchMedia("(max-width: 576px)").matches;

  function updateControls(next: QueueControlsState) {
    setControls(next);
    saveControls(tab, next);
    setPage(1);
  }

  const all = data?.items.filter((c) => c.tab === tab) ?? [];
  const matching = applyControls(all, controls);
  const paged = paginate(matching, page, controls.perPage);
  const items = paged.items;

  // Drop selections that no longer exist after a reload.
  React.useEffect(() => {
    setSelected((s) => new Set([...s].filter((id) => all.some((c) => c.id === id))));
  }, [data]);

  function toggle(id: string, on: boolean) {
    setSelected((s) => {
      const next = new Set(s);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  const picked = all.filter((c) => selected.has(c.id));
  const files = picked.flatMap((c) => (c.members?.length ? c.members : [c]));
  const busyPicked = picked.some((c) => BUSY.includes(c.status) || c.status === "sent");

  async function run(action: () => Promise<unknown>, done: string) {
    try {
      await action();
      Toast.success(done);
      setSelected(new Set());
      load();
    } catch (e) {
      Toast.error(e);
    }
  }

  const selectionActions: SelectionAction[] = [
    {
      text: "Make one post",
      primary: true,
      disabled: files.length < 2 || files.length > MAX_POST_FILES || busyPicked,
      onClick: () => run(() => runOperation("post_create", { item_ids: files.map((f) => f.id) }),
        `${files.length} files are now one post.`),
    },
    {
      text: "Split into separate posts",
      disabled: !picked.some((c) => c.kind === "set") || busyPicked,
      onClick: () => run(() => Promise.all(picked.filter((c) => c.kind === "set")
        .map((c) => runOperation("post_split", { post_id: c.id }))), "Split into separate posts."),
    },
    {
      text: `Remove "${data?.tags.queue.name ?? "imaglr"}" tag`,
      disabled: busyPicked,
      onClick: () => {
        const tag = data?.tags.queue.name ?? "imaglr";
        if (!window.confirm(`Remove the "${tag}" tag in Stash from ${picked.length} item(s)? They leave this page. ` +
          "Nothing on imaglr is changed and nothing is deleted.")) return;
        void run(() => Promise.all(picked.map((c) => runOperation("remove_from_queue", { item_id: c.id }))),
          "Removed from this page.");
      },
    },
  ];

  const url = (c: Card) => `${ROUTE}?tab=${tab}&open=${c.id}`;
  const selecting = selected.size > 0;

  let body: React.ReactNode;
  if (error) {
    body = (
      <div className="alert alert-danger">
        Couldn't load the queue: {error}{" "}
        <Button variant="link" className="p-0" onClick={load}>Try again</Button>
      </div>
    );
  } else if (!data) {
    body = LoadingIndicator ? <LoadingIndicator /> : <p className="text-muted">Loading…</p>;
  } else if (all.length === 0) {
    body = <div className="imaglr-empty text-muted">{EMPTY[tab](data.tags.queue.name)}</div>;
  } else if (matching.length === 0) {
    body = <p className="text-muted imaglr-empty">Nothing matches these filters.</p>;
  } else if (controls.view === "list") {
    body = (
      <Table striped bordered size="sm" className="imaglr-table">
        <tbody>
          {items.map((c) => (
            <tr key={c.id}>
              <td className="select-col">
                <input type="checkbox" className="mousetrap" checked={selected.has(c.id)} aria-label={`Select ${c.title}`}
                  onChange={(e) => toggle(c.id, e.target.checked)} />
              </td>
              <td className="imaglr-table-thumb"><CardImage card={c} /></td>
              <td>
                <Link to={url(c)}>{c.title}</Link>
                <div className="small text-muted">{cardDetail(c)}</div>
              </td>
              <td className="imaglr-table-status"><Badge variant={STATUS_VARIANTS[c.status]}>{STATUS_LABELS[c.status]}</Badge></td>
            </tr>
          ))}
        </tbody>
      </Table>
    );
  } else {
    const w = isMobile ? undefined : cardWidth(width, controls.zoom);
    body = (
      <div className="row justify-content-center imaglr-cards">
        {items.map((c) =>
          GridCard ? (
            <GridCard
              key={c.id}
              className={`image-card zoom-${controls.zoom} imaglr-grid-card${c.id === openId ? " imaglr-card-highlight" : ""}`}
              linkClassName="image-card-link"
              width={w}
              url={url(c)}
              title={c.title}
              image={<CardImage card={c} />}
              overlays={<CardOverlays card={c} />}
              details={<div className="image-card__details"><span>{cardDetail(c)}</span></div>}
              selecting={selecting}
              selected={selected.has(c.id)}
              onSelectedChanged={(on: boolean) => toggle(c.id, on)}
            />
          ) : (
            <FallbackCard key={c.id} card={c} url={url(c)} width={w} />
          ),
        )}
      </div>
    );
  }

  return (
    <div ref={box}>
      <Toolbar
        tab={tab}
        controls={controls}
        items={all}
        selected={selected.size}
        selectionActions={selectionActions}
        onChange={updateControls}
        onSelectAll={() => setSelected(new Set(matching.map((c) => c.id)))}
        onSelectNone={() => setSelected(new Set())}
        onRefresh={load}
        onSendAll={matching.length ? () => setSendAll(selected.size ? [...selected] : matching.map((c) => c.id)) : undefined}
      />
      {body}
      {matching.length ? (
        <Pager page={paged.page} perPage={controls.perPage} total={matching.length}
          onChange={(p) => { setPage(p); window.scrollTo({ top: 0 }); }} />
      ) : null}
      {sendAll ? (
        <SendAllDialog itemIds={sendAll} selected={selected.size > 0} onClose={(sent) => {
          setSendAll(null);
          if (sent) {
            setSelected(new Set());
            load();
          }
        }} />
      ) : null}
      {openId ? (
        <Editor
          itemId={openId}
          onClose={(changed) => {
            history.replace({ search: `?tab=${tab}` });
            if (changed) load();
          }}
        />
      ) : null}
    </div>
  );
}

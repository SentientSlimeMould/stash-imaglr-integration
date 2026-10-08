// SPDX-License-Identifier: AGPL-3.0-only
// The Clips and Images tabs: what's waiting to be sent, shown with Stash's own list toolbar and cards.
// A card links to its editor (?open=<id>), so tapping opens it and it can also be opened in a new tab.
import React from "react";
import { edgeLabel } from "../lib/video.ts";
import { runOperation } from "../api.ts";
import { Editor } from "../editor/Editor.tsx";
import { applyControls, changesWhatIsListed, loadControls, paginate, saveControls, type QueueControlsState } from "../lib/sort.ts";
import { fmtDims } from "../lib/format.ts";
import { MAX_POST_FILES } from "../lib/imageActions.ts";
import { STATUS_LABELS, STATUS_VARIANTS, type Card, type QueueResponse } from "../model.ts";
import { ROUTE } from "../routes.ts";
import { CardGrid, type GridItem } from "./CardGrid.tsx";
import { Pager } from "./Paging.tsx";
import { SendAllDialog } from "./SendAllDialog.tsx";
import { Toolbar, type SelectionAction } from "./Toolbar.tsx";
import { ConfirmDialog } from "../ConfirmDialog.tsx";

const BUSY = ["exporting", "sending"];

function cardDetail(card: Card): string {
  const count = card.members?.length ?? 0;
  if (count) return `${count} files in one post`;
  if (card.kind === "clip") {
    if (card.output_note) return card.output_note; // e.g. "GIF · 9.4 MB · 480 px · 10 fps"
    const how = card.send_format === "gif" || card.send_format === "webp"
      ? [card.send_format === "webp" ? "WebP" : "GIF", card.loop === "boomerang" ? "boomerang" : null, card.gif_width ? `${card.gif_width} px` : null].filter(Boolean).join(" ")
      : [card.send_codec === "hevc" ? "H.265" : null, card.max_edge ? edgeLabel(card.max_edge) : null].filter(Boolean).join(" ");
    return [card.whole_scene ? "whole scene" : null, `${(card.duration ?? 0).toFixed(1)} s`, fmtDims(card.width, card.height), how || null]
      .filter(Boolean).join(" · ");
  }
  return [card.format?.toUpperCase(), fmtDims(card.width, card.height), card.animated ? "animated" : null]
    .filter(Boolean)
    .join(" · ");
}

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

export interface QueueProps {
  data: QueueResponse | null;
  error: string | null;
  load: () => Promise<unknown>;
}

export function QueueTab({ tab, openId, data, error, load }: { tab: "clips" | "images"; openId: string | null } & QueueProps) {
  const { Button } = PluginApi.libraries.Bootstrap;
  const { useHistory } = PluginApi.libraries.ReactRouterDOM;
  const { LoadingIndicator } = PluginApi.components;
  const Toast = PluginApi.hooks.useToast();
  const history = useHistory();

  const [controls, setControls] = React.useState<QueueControlsState>(() => loadControls(tab));
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [sendAll, setSendAll] = React.useState<string[] | null>(null);
  const [confirmRemove, setConfirmRemove] = React.useState(false);
  const [page, setPage] = React.useState(1);

  function updateControls(next: QueueControlsState) {
    if (changesWhatIsListed(controls, next)) setPage(1); // view and zoom changes keep the page, like Stash
    setControls(next);
    saveControls(tab, next);
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

  // Stills only exist in the plugin, so removing them deletes them; everything else just loses the tag in Stash.
  const stills = picked.filter((c) => c.kind === "still" || c.members?.every((m) => m.kind === "still"));
  const others = picked.length - stills.length;
  const queueTagName = data?.tags.queue.name ?? "imaglr";
  const removeTitle = stills.length && !others ? `Delete ${stills.length === 1 ? "still" : "stills"}` : `Remove "${queueTagName}" tag`;
  const removeQuestion = [
    others ? `Remove the "${queueTagName}" tag in Stash from ${others === 1 ? "this item" : `${others} items`}? ${others === 1 ? "It leaves" : "They leave"} this page; nothing in Stash is deleted.` : null,
    stills.length ? `${stills.length === 1 ? "1 still" : `${stills.length} stills`} will be deleted (stills only exist in the plugin).` : null,
    "Nothing on imaglr is changed.",
  ].filter(Boolean).join(" ");

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
      onClick: () => run(() => runOperation("post_split", { post_ids: picked.filter((c) => c.kind === "set").map((c) => c.id) }),
        "Split into separate posts."),
    },
    {
      text: removeTitle,
      disabled: busyPicked,
      onClick: () => setConfirmRemove(true),
    },
  ];

  const url = (c: Card) => `${ROUTE}?tab=${tab}&open=${c.id}`;
  const selecting = selected.size > 0;

  let body: React.ReactNode;
  const problem = error ? (
    <div className="alert alert-danger">
      Couldn't load the list: {error}{" "}
      <Button variant="link" className="p-0 imaglr-touch" onClick={load}>Try again</Button>
    </div>
  ) : null;
  if (error && !data) {
    body = problem;
  } else if (!data) {
    body = LoadingIndicator ? <LoadingIndicator /> : <p className="text-muted">Loading…</p>;
  } else if (all.length === 0) {
    body = <div className="imaglr-empty text-muted">{EMPTY[tab](data.tags.queue.name)}</div>;
  } else if (matching.length === 0) {
    body = <p className="text-muted imaglr-empty">Nothing matches these filters.</p>;
  } else {
    const gridItems: GridItem[] = items.map((c) => ({
      id: c.id,
      title: c.title,
      url: url(c),
      thumb: c.thumb,
      preview: c.preview,
      portrait: (c.height ?? 0) > (c.width ?? 0),
      detail: cardDetail(c),
      badge: { text: STATUS_LABELS[c.status], variant: STATUS_VARIANTS[c.status] },
      count: c.members?.length,
    }));
    body = <CardGrid items={gridItems} view={controls.view} zoom={controls.zoom} highlightId={openId} selected={selected} onToggle={toggle} />;
  }

  return (
    <div>
      {data && problem}
      <Toolbar
        tab={tab}
        controls={controls}
        items={all}
        selected={selected.size}
        selectionActions={selectionActions}
        onChange={updateControls}
        onSelectAll={() => setSelected(new Set(items.map((c) => c.id)))}
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
      {confirmRemove ? (
        <ConfirmDialog title={removeTitle} accept={stills.length && stills.length === picked.length ? "Delete" : "Remove"} variant="danger"
          onAccept={() => {
            setConfirmRemove(false);
            void run(() => runOperation("remove_from_queue", { item_ids: picked.map((c) => c.id) }), "Removed from this page.");
          }}
          onCancel={() => setConfirmRemove(false)}>
          {removeQuestion}
        </ConfirmDialog>
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

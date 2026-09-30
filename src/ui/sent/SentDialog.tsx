// SPDX-License-Identifier: AGPL-3.0-only
// Details of one sent post, opened from a Sent card (?tab=sent&open=<id>) like the editor is from
// the queue tabs: where it went, the tags imaglr kept and dropped, the caption, and a retry when
// queueing or publishing failed after the upload.
import React from "react";
import { baseUrl, runOperation } from "../api.ts";
import { fmtDate } from "../lib/format.ts";
import { imaglrLink, SENT_AS_LABELS, stashLink } from "../lib/send.ts";
import type { SentItem } from "../model.ts";

interface Props {
  itemId: string;
  onClose: (changed: boolean) => void;
}

export function SentDialog({ itemId, onClose }: Props) {
  const { Modal, Button, Badge, Alert } = PluginApi.libraries.Bootstrap;
  const { Link } = PluginApi.libraries.ReactRouterDOM;
  const { LoadingIndicator } = PluginApi.components;
  const Toast = PluginApi.hooks.useToast();
  const [item, setItem] = React.useState<SentItem | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const changed = React.useRef(false);

  const load = React.useCallback(() => {
    runOperation<{ item: SentItem }>("sent_detail", { item_id: itemId }).then((r) => setItem(r.item), (e: Error) => setError(e.message));
  }, [itemId]);
  React.useEffect(load, [load]);

  async function retry() {
    if (!item) return;
    setBusy(true);
    try {
      await runOperation("retry_follow_up", { item_id: item.id });
      Toast.success(item.action === "publish" ? "Published." : "Added to the queue.");
      changed.current = true;
      load();
    } catch (e) {
      Toast.error(e);
    } finally {
      setBusy(false);
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

  let body: React.ReactNode;
  if (error) {
    body = <Alert variant="danger">{error}</Alert>;
  } else if (!item) {
    body = LoadingIndicator ? <LoadingIndicator /> : <p className="text-muted">Loading…</p>;
  } else {
    body = (
      <>
        {item.followup_failed ? (
          <Alert variant="warning">
            {item.error_detail}{" "}
            <Button variant="link" className="p-0 align-baseline" disabled={busy} onClick={retry}>
              {item.action === "publish" ? "Retry publishing" : "Retry adding to queue"}
            </Button>
          </Alert>
        ) : item.error_detail ? <Alert variant="warning">{item.error_detail}</Alert> : null}
        <ol className="imaglr-strip">
          {item.files.map((f) => {
            const to = stashLink(f);
            const img = f.thumb ? <img src={baseUrl() + f.thumb} alt="" /> : null;
            return (
              <li key={f.id} className="imaglr-strip-item" title={f.title}>
                {to ? <Link to={to} title={`${f.title} in Stash`}>{img}</Link> : img}
              </li>
            );
          })}
        </ol>
        <dl className="row imaglr-sent-facts">
          <dt className="col-4 col-sm-3">{item.kind === "set" ? "Files" : item.kind === "clip" ? "Clip" : item.kind === "still" ? "Still" : "Image"}</dt>
          <dd className="col-8 col-sm-9">
            {item.kind === "set" ? `${item.files.length} files in one post`
              : stashLink(item.files[0] ?? {}) ? <Link to={stashLink(item.files[0])!} title="Open in Stash">{item.title}</Link> : item.title}
          </dd>
          <dt className="col-4 col-sm-3">Sent as</dt>
          <dd className="col-8 col-sm-9">
            <Badge variant={item.sent_as === "publish" ? "success" : "primary"}>{SENT_AS_LABELS[item.sent_as]}</Badge>{" "}
            {item.blog ? <>on <strong>{item.blog}</strong></> : null}
          </dd>
          <dt className="col-4 col-sm-3">When</dt>
          <dd className="col-8 col-sm-9">{fmtDate(item.sent_at)}</dd>
          <dt className="col-4 col-sm-3">On imaglr</dt>
          <dd className="col-8 col-sm-9">
            <a href={imaglrLink(item.sent_as, item.post_url)} target="_blank" rel="noreferrer">
              {item.sent_as === "draft" ? "Open imaglr drafts" : "Open the post"}
            </a>
          </dd>
          <dt className="col-4 col-sm-3">Tags</dt>
          <dd className="col-8 col-sm-9">
            {item.tags.length ? item.tags.map((t) => <Badge key={t} variant="secondary" className="tag-item">{t}</Badge>) : <span className="text-muted">None</span>}
          </dd>
          {item.dropped_tags.length ? (
            <>
              <dt className="col-4 col-sm-3">Dropped by imaglr</dt>
              <dd className="col-8 col-sm-9">
                {item.dropped_tags.map((tag) => (
                  <span key={tag} className="imaglr-dropped">
                    <Badge variant="secondary" className="tag-item">{tag}</Badge>
                    <Button variant="link" size="sm" className="p-0 align-baseline" onClick={() => alwaysDrop(tag)}>Always drop</Button>
                  </span>
                ))}
              </dd>
            </>
          ) : null}
          {item.caption ? (
            <>
              <dt className="col-4 col-sm-3">Caption</dt>
              <dd className="col-8 col-sm-9 imaglr-caption">{item.caption}</dd>
            </>
          ) : null}
        </dl>
      </>
    );
  }

  return (
    // Like Stash's own dialogs (ModalComponent): clicking outside or pressing Escape does nothing.
    <Modal show onHide={() => undefined} keyboard={false} size="lg" scrollable>
      <Modal.Header>
        <Modal.Title>
          Sent to imaglr {item ? <small className="text-muted">{SENT_AS_LABELS[item.sent_as]}</small> : null}
        </Modal.Title>
      </Modal.Header>
      <Modal.Body>{body}</Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={() => onClose(changed.current)}>Close</Button>
      </Modal.Footer>
    </Modal>
  );
}

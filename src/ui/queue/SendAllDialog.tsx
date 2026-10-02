// SPDX-License-Identifier: AGPL-3.0-only
// Confirmation for "Send all" / "Send selected": what goes where, what is skipped and why.
// Never publishes straight away: items whose action is Publish now are saved as drafts.
import React from "react";
import { runOperation } from "../api.ts";
import { gifCounts, summarisePlan, type PlanEntry } from "../lib/sendAll.ts";
import { LONG_GIF_SECONDS } from "../lib/gif.ts";
import type { Blog } from "../model.ts";

export function SendAllDialog({ itemIds, selected, onClose }: {
  itemIds: string[];
  selected: boolean;
  onClose: (sent: boolean) => void;
}) {
  const { Modal, Button, Form, Alert } = PluginApi.libraries.Bootstrap;
  const Toast = PluginApi.hooks.useToast();
  const [plan, setPlan] = React.useState<PlanEntry[] | null>(null);
  const [blogs, setBlogs] = React.useState<Blog[]>([]);
  const [fallbackBlog, setFallbackBlog] = React.useState<number | null>(null);
  const [longAsVideo, setLongAsVideo] = React.useState(true);
  const [gifFallback, setGifFallback] = React.useState(true);
  const [busy, setBusy] = React.useState(false);

  const preview = React.useCallback(() => {
    runOperation<{ plan: PlanEntry[] }>("send_all", { item_ids: itemIds, dry_run: true })
      .then((r) => setPlan(r.plan), (e: Error) => { Toast.error(e); onClose(false); });
  }, [itemIds]);

  React.useEffect(() => {
    preview();
    runOperation<{ blogs: Blog[] }>("blogs_list").then((r) => setBlogs(r.blogs.filter((b) => !b.paused_reason)), () => undefined);
  }, [preview]);

  if (!plan) {
    const { LoadingIndicator } = PluginApi.components;
    return (
      <Modal show onHide={() => undefined} keyboard={false}>
        <Modal.Header><Modal.Title>{selected ? "Send selected" : "Send all"}</Modal.Title></Modal.Header>
        <Modal.Body>{LoadingIndicator ? <LoadingIndicator message="Checking…" /> : <p className="text-muted">Checking…</p>}</Modal.Body>
        <Modal.Footer><Button variant="secondary" onClick={() => onClose(false)}>Cancel</Button></Modal.Footer>
      </Modal>
    );
  }
  const noBlog = plan.filter((e) => e.skip === "no_blog");
  const fallback = blogs.find((b) => b.id === fallbackBlog) ?? null;
  const { sending, skipped, downgraded, total: ready } = summarisePlan(plan, fallback);
  const gifs = gifCounts(plan);

  async function send() {
    setBusy(true);
    try {
      if (fallbackBlog) {
        await Promise.all(noBlog.map((e) => runOperation("item_update", { item_id: e.id, changes: { blog_id: fallbackBlog } })));
      }
      const r = await runOperation<{ plan: PlanEntry[] }>("send_all", {
        item_ids: itemIds, long_gifs_as_video: longAsVideo, gif_fallback: gifFallback,
      });
      const started = r.plan.filter((e) => !e.skip).length;
      Toast.success(`Sending ${started} ${started === 1 ? "item" : "items"}. Progress shows on each card.`);
      onClose(true);
    } catch (e) {
      Toast.error(e);
      setBusy(false);
    }
  }

  return (
    <Modal show onHide={() => undefined} keyboard={false}>
      <Modal.Header>
        <Modal.Title>{selected ? "Send selected" : "Send all"}</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {sending.length ? (
          <ul className="imaglr-plan">
            {sending.map(([what, n]) => <li key={what}><strong>{n}</strong> to {what}</li>)}
          </ul>
        ) : <p>Nothing can be sent yet.</p>}
        {downgraded ? (
          <Alert variant="info">
            {downgraded} {downgraded === 1 ? "item is" : "items are"} set to Publish now and will be saved as drafts
            instead. Send all never publishes straight away; publish from the editor or on imaglr.
          </Alert>
        ) : null}
        {gifs.gifs ? (
          <div className="imaglr-plan-gifs">
            <div>
              {gifs.gifs} {gifs.gifs === 1 ? "clip will be a GIF" : "clips will be GIFs"}.
              {gifs.long ? ` ${gifs.long} ${gifs.long === 1 ? "is" : "are"} longer than ${LONG_GIF_SECONDS} seconds — send ${gifs.long === 1 ? "it" : "them"} as a video instead?` : null}
            </div>
            {gifs.long ? (
              <Form.Check id="imaglr-long-gifs" type="checkbox" checked={longAsVideo}
                label={`Send the ${gifs.long === 1 ? "long clip" : "long clips"} as ${gifs.long === 1 ? "a video" : "videos"}`}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setLongAsVideo(e.target.checked)} />
            ) : null}
            <Form.Check id="imaglr-gif-fallback" type="checkbox" checked={gifFallback}
              label="If a GIF can't be made small enough, send it as a video."
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setGifFallback(e.target.checked)} />
          </div>
        ) : null}
        {noBlog.length && blogs.length ? (
          <Form.Group>
            <Form.Label>{noBlog.length} {noBlog.length === 1 ? "item has" : "items have"} no blog chosen. Send {noBlog.length === 1 ? "it" : "them"} to:</Form.Label>
            <Form.Control as="select" className="text-input" value={fallbackBlog ?? ""}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setFallbackBlog(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Skip {noBlog.length === 1 ? "it" : "them"}</option>
              {blogs.map((b) => <option key={b.id} value={b.id}>{b.label} (uses its default action)</option>)}
            </Form.Control>
          </Form.Group>
        ) : null}
        {skipped.length ? (
          <div className="small text-muted">Skipped: {skipped.map(([reason, n]) => `${n} ${reason}`).join(", ")}.</div>
        ) : null}
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={() => onClose(false)}>Cancel</Button>
        <Button variant="primary" disabled={!ready || busy} onClick={send}>
          {busy ? "Starting…" : `Send ${ready}`}
        </Button>
      </Modal.Footer>
    </Modal>
  );
}

// SPDX-License-Identifier: AGPL-3.0-only
// Editor for one queued item or post: files, crop, tags, caption, blog and action, then Send.
// Full screen on phones (see styles.css). Edits are saved when sending or closing.
import React from "react";
import { baseUrl, runOperation } from "../api.ts";
import { ASPECTS, overlayRect } from "../lib/crop.ts";
import type { Aspect } from "../lib/types.ts";
import { ACTION_LABELS, blogProblem, effectiveAction, pickBlog, sendButtonLabel, stashLink } from "../lib/send.ts";
import { STATUS_LABELS, type FileCard, type ItemDetail, type SendAction } from "../model.ts";
import { ConfirmDialog } from "../ConfirmDialog.tsx";
import { ClipPanel, type ClipState } from "./ClipPanel.tsx";
import { TagField } from "./TagField.tsx";

interface Props {
  itemId: string;
  onClose: (changed: boolean) => void;
}

const BUSY = ["exporting", "sending"];

function CropPreview({ file, aspect, position }: { file: FileCard; aspect: Aspect; position: number }) {
  const box = React.useRef<HTMLDivElement>(null);
  const [size, setSize] = React.useState({ w: 0, h: 0, sw: file.width ?? 0, sh: file.height ?? 0 });

  function measure(img?: HTMLImageElement) {
    const el = box.current;
    if (!el) return;
    setSize((s) => ({
      w: el.clientWidth,
      h: el.clientHeight,
      sw: img?.naturalWidth || s.sw,
      sh: img?.naturalHeight || s.sh,
    }));
  }

  React.useEffect(() => {
    const onResize = () => measure();
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const rect = overlayRect(size.w, size.h, size.sw, size.sh, aspect, position);
  const src = file.image ?? file.thumb;
  return (
    <div ref={box} className="imaglr-preview">
      {src ? <img src={baseUrl() + src} alt="" onLoad={(e) => measure(e.currentTarget)} /> : null}
      {rect.axis !== "none" ? (
        <div className="imaglr-crop" style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }} />
      ) : null}
    </div>
  );
}

function FileStrip({ files, disabled, onArrange }: {
  files: FileCard[];
  disabled: boolean;
  onArrange: (ids: string[]) => void;
}) {
  const { Link } = PluginApi.libraries.ReactRouterDOM;
  const ids = files.map((f) => f.id);
  const move = (from: number, to: number) => {
    const next = [...ids];
    next.splice(to, 0, next.splice(from, 1)[0]);
    onArrange(next);
  };
  return (
    <ol className="imaglr-strip">
      {files.map((f, n) => (
        <li key={f.id} className="imaglr-strip-item" title={f.title}>
          {stashLink(f) ? <Link to={stashLink(f)!} title={`${f.title} in Stash`}>{f.thumb ? <img src={baseUrl() + f.thumb} alt="" /> : null}</Link>
            : f.thumb ? <img src={baseUrl() + f.thumb} alt="" /> : null}
          <span className="imaglr-strip-number">{n + 1}</span>
          {disabled ? null : (
            <div className="imaglr-strip-actions">
              <button type="button" aria-label="Move earlier" disabled={n === 0} onClick={() => move(n, n - 1)}>◀</button>
              <button type="button" aria-label="Remove from this post" onClick={() => onArrange(ids.filter((i) => i !== f.id))}>×</button>
              <button type="button" aria-label="Move later" disabled={n === files.length - 1} onClick={() => move(n, n + 1)}>▶</button>
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}

export function Editor({ itemId, onClose }: Props) {
  const { Modal, Button, Form, ButtonGroup, Alert, ProgressBar } = PluginApi.libraries.Bootstrap;
  const { Link } = PluginApi.libraries.ReactRouterDOM;
  const Toast = PluginApi.hooks.useToast();
  const [detail, setDetail] = React.useState<ItemDetail | null>(null);
  const [tags, setTags] = React.useState<string[]>([]);
  const [caption, setCaption] = React.useState("");
  const [crop, setCrop] = React.useState<{ aspect: Aspect; position: number }>({ aspect: "original", position: 0.5 });
  const [trim, setTrim] = React.useState({ inS: 0, outS: 0, mute: false });
  const [blogId, setBlogId] = React.useState<number | null>(null);
  const [action, setAction] = React.useState<SendAction | null>(null);
  const [confirmPublish, setConfirmPublish] = React.useState(false);
  const [confirmRemove, setConfirmRemove] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [changed, setChanged] = React.useState(false);
  const [dirty, setDirty] = React.useState(false);

  const load = React.useCallback(() => {
    runOperation<ItemDetail>("item_detail", { item_id: itemId }).then((d) => {
      setDetail(d);
      setTags(d.item.tags);
      setCaption(d.item.caption);
      setCrop(d.item.crop);
      setTrim({ inS: d.item.in_s ?? 0, outS: d.item.out_s ?? 0, mute: d.item.mute });
      setBlogId(d.item.blog_id);
      setAction(d.item.action);
      setDirty(false);
    }, (e: Error) => {
      Toast.error(e);
      onClose(true);
    });
  }, [itemId]);

  React.useEffect(load, [load]);

  if (!detail) return null;
  const { item, files, blogs } = detail;
  const queueTag = detail.queue_tag;
  const locked = BUSY.includes(item.status) || busy;
  const blog = pickBlog(blogs, blogId);
  const sendAction = effectiveAction(blog, action);
  const problem = blog ? blogProblem(blog) : null;
  const single = files.length === 1 && item.kind !== "set";
  const isClip = item.kind === "clip";

  function edit<T>(setter: (v: T) => void) {
    return (value: T) => {
      setter(value);
      setDirty(true);
    };
  }

  async function save() {
    if (!dirty) return;
    await runOperation("item_update", {
      item_id: item.id,
      changes: {
        tags, caption, crop, blog_id: blogId, action,
        ...(isClip ? { in_s: trim.inS, out_s: trim.outS, mute: trim.mute } : {}),
      },
    });
    setDirty(false);
    setChanged(true);
  }

  function cancel() {
    onClose(changed);
  }

  async function send() {
    if (sendAction === "publish" && !confirmPublish) {
      setConfirmPublish(true);
      return;
    }
    setBusy(true);
    try {
      await save();
      await runOperation("send", { item_id: item.id, blog_id: blog?.id, action });
      onClose(true);
    } catch (e) {
      Toast.error(e);
      setBusy(false);
      setConfirmPublish(false);
    }
  }

  async function arrange(ids: string[]) {
    try {
      await save();
      const result = await runOperation<{ post_id: string | null }>("post_arrange", { item_id: item.id, item_ids: ids });
      setChanged(true);
      if (result.post_id) load();
      else onClose(true);
    } catch (e) {
      Toast.error(e);
    }
  }

  async function saveStill(t: number) {
    try {
      await runOperation("still_create", { item_id: item.id, t });
      setChanged(true);
      Toast.success(`Still saved at ${t.toFixed(1)} s. It's on the Images tab.`);
    } catch (e) {
      Toast.error(e);
    }
  }

  async function cancelSend() {
    await runOperation("cancel", { item_id: item.id }).catch((e: Error) => Toast.error(e));
    onClose(true);
  }

  const removeLabel = item.kind === "still"
    ? "Delete still"
    : `Remove "${queueTag}" tag${item.kind === "set" ? "s" : ""}`;

  const removeQuestion = item.kind === "still"
    ? "Delete this still? It only exists in the plugin."
    : `Remove the "${queueTag}" tag in Stash${item.kind === "set" ? " from every file in this post" : ""}? ` +
      "It leaves this page. Nothing on imaglr is changed and nothing is deleted.";

  async function remove() {
    try {
      await runOperation("remove_from_queue", { item_id: item.id });
      onClose(true);
    } catch (e) {
      setConfirmRemove(false);
      Toast.error(e);
    }
  }

  const kindLabel = item.kind === "set" ? "Files" : item.kind === "clip" ? "Clip" : item.kind === "still" ? "Still" : "Image";
  // The name links to where the file lives in Stash: the image, or the scene's Markers tab for a clip.
  const sourceLink = item.kind === "set" ? null : stashLink(files[0] ?? {});
  const itemName = item.kind === "set" ? `${files.length} files in one post`
    : sourceLink ? <Link to={sourceLink} title={item.kind === "clip" ? "Open the scene in Stash at this clip (its marker is on the Markers tab)" : "Open in Stash"}>{item.source_title}</Link>
    : item.source_title;


  return (
    // Like Stash's own dialogs (ModalComponent): clicking outside or pressing Escape does nothing;
    // leave with Cancel or the send button.
    <Modal show onHide={() => undefined} keyboard={false} size="lg" dialogClassName="imaglr-editor" scrollable>
      <Modal.Header>
        <Modal.Title>
          Post to imaglr <small className="text-muted">{STATUS_LABELS[item.status]}</small>
        </Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <dl className="row imaglr-item-facts">
          <dt className="col-3 col-sm-2">{kindLabel}</dt>
          <dd className="col-9 col-sm-10">{itemName}</dd>
        </dl>
        {item.error_detail && !BUSY.includes(item.status) ? <Alert variant="warning">{item.error_detail}</Alert> : null}
        {BUSY.includes(item.status) ? (
          <div className="mb-3">
            <ProgressBar now={Math.round(item.progress * 100)} label={STATUS_LABELS[item.status]} />
          </div>
        ) : null}

        {item.hdr_warning ? (
          <Alert variant="info">This video is HDR. Colours may look flatter on imaglr (HDR isn't converted).</Alert>
        ) : null}
        {isClip ? (
          <ClipPanel
            sceneId={files[0].stash_scene_id}
            imageId={files[0].stash_marker_id ? null : files[0].stash_image_id}
            value={{ ...trim, crop }}
            disabled={locked}
            onChange={(v: ClipState) => {
              edit(setTrim)({ inS: v.inS, outS: v.outS, mute: v.mute });
              setCrop(v.crop);
            }}
            onSaveStill={saveStill}
          />
        ) : single ? (
          <>
            <CropPreview file={files[0]} aspect={crop.aspect} position={crop.position} />
            <Form.Group className="mt-2">
              <Form.Label>Crop</Form.Label>
              <div>
                <ButtonGroup className="imaglr-segmented">
                  {(Object.keys(ASPECTS) as Aspect[]).map((a) => (
                    <Button key={a} variant={crop.aspect === a ? "primary" : "secondary"} disabled={locked}
                      onClick={() => edit(setCrop)({ ...crop, aspect: a })}>
                      {a === "original" ? "Original" : a}
                    </Button>
                  ))}
                </ButtonGroup>
              </div>
              {crop.aspect !== "original" ? (
                <Form.Control type="range" min={0} max={1} step={0.01} value={crop.position} disabled={locked}
                  aria-label="Crop position" className="mt-2"
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                    edit(setCrop)({ ...crop, position: Number(e.target.value) })} />
              ) : null}
            </Form.Group>
          </>
        ) : (
          <>
            <p className="text-muted mb-1">Files in this post, in order:</p>
            <FileStrip files={files} disabled={locked} onArrange={arrange} />
            {locked ? null : (
              <Button variant="link" className="p-0 mb-2" onClick={() => arrange([])}>
                Split into separate posts
              </Button>
            )}
          </>
        )}

        <TagField tags={tags} suggestions={detail.suggestions} lowercase={detail.lowercase_tags} disabled={locked}
          onChange={edit(setTags)} />

        <Form.Group className="mt-3">
          <Form.Label>Caption <small className="text-muted">(optional)</small></Form.Label>
          <Form.Control className="text-input" as="textarea" rows={3} value={caption} disabled={locked}
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => edit(setCaption)(e.target.value)} />
        </Form.Group>

        {blogs.length > 1 ? (
          <Form.Group>
            <Form.Label>Blog</Form.Label>
            <Form.Control className="text-input" as="select" value={blogId ?? ""} disabled={locked}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
                edit(setBlogId)(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Choose a blog…</option>
              {blogs.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
            </Form.Control>
          </Form.Group>
        ) : null}

        <Form.Group>
          <Form.Label>
            Send as{" "}
            {blog ? <small className="text-muted">(default for {blog.label}: {ACTION_LABELS[blog.default_action].toLowerCase()})</small> : null}
          </Form.Label>
          <div>
            <ButtonGroup className="imaglr-segmented">
              {(Object.keys(ACTION_LABELS) as SendAction[]).map((a) => (
                <Button key={a} variant={sendAction === a ? "primary" : "secondary"} disabled={locked}
                  onClick={() => {
                    edit(setAction)(a);
                    setConfirmPublish(false);
                  }}>
                  {ACTION_LABELS[a]}
                </Button>
              ))}
            </ButtonGroup>
          </div>
        </Form.Group>
        {blogs.length === 0 ? <Alert variant="info">Add your imaglr blog first: use the Settings button on the page.</Alert> : null}
        {problem ? <Alert variant="warning">{problem}</Alert> : null}
      </Modal.Body>
      <Modal.Footer className="imaglr-editor-footer">
        {BUSY.includes(item.status) ? (
          <Button variant="secondary" onClick={cancelSend}>Stop sending</Button>
        ) : (
          <>
            <Button variant="link" className="text-danger mr-auto" onClick={() => setConfirmRemove(true)} disabled={locked}>
              {removeLabel}
            </Button>
            <Button variant="secondary" onClick={cancel}>Cancel</Button>
            {confirmPublish ? (
              <span className="imaglr-confirm">
                Posts publicly on {blog?.label} right away.
                <Button variant="secondary" onClick={() => setConfirmPublish(false)}>Cancel</Button>
                <Button variant="danger" onClick={send} disabled={busy}>Publish now</Button>
              </span>
            ) : (
              <Button variant="primary" onClick={send} disabled={locked || !blog || !!problem}>
                {busy ? "Starting…" : sendButtonLabel(sendAction, blog)}
              </Button>
            )}
          </>
        )}
      </Modal.Footer>
      {confirmRemove ? (
        <ConfirmDialog title={removeLabel} accept={item.kind === "still" ? "Delete" : "Remove tag"} variant="danger"
          onAccept={remove} onCancel={() => setConfirmRemove(false)}>
          {removeQuestion}
        </ConfirmDialog>
      ) : null}
    </Modal>
  );
}

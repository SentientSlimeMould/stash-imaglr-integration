// SPDX-License-Identifier: AGPL-3.0-only
// The save review: before a post goes into your library, each of its imaglr tags with what it will become in
// Stash (tags, performers, a studio, or nothing) and why. Change any of them, create a new Stash tag for one
// that matches nothing, add more, and tick Remember to use the same choice for every post from now on (an import
// rule, kept in the plugin; never a Stash alias, which would feed Stash's Auto Tag). Stash's own modal, badges
// and select.
import React from "react";
import { runOperation } from "../api.ts";
import type { ImaglrPost, SaveState, StashRef } from "../lib/posts.ts";

export type TargetKind = "tag" | "performer" | "studio";
export interface Target {
  kind: TargetKind;
  id?: string;
  name: string;
  create?: boolean; // a new Stash tag, made when the post is saved
}
interface Row {
  tag: string;
  targets: Target[];
  source: "rule" | "match" | "suggested" | "none";
  remember: boolean;
}

const WHY: Record<Row["source"], string> = {
  rule: "your import rule",
  match: "same name in Stash",
  suggested: "from your tag rule",
  none: "",
};
const KIND_LABELS: Record<TargetKind, string> = { tag: "Tag", performer: "Performer", studio: "Studio" };

/** One chosen target, as a badge with a remove button. */
export function TargetBadge({ target, onRemove }: { target: Target; onRemove?: () => void }) {
  const { Icon } = PluginApi.components;
  const fa = PluginApi.libraries.FontAwesomeSolid;
  const icon = target.kind === "performer" ? fa.faUser : target.kind === "studio" ? fa.faVideo : fa.faTag;
  return (
    <span className="tag-item badge badge-secondary imaglr-target">
      <Icon icon={icon} /> {target.name}{target.create ? " (new)" : ""}
      {onRemove ? <button type="button" className="imaglr-target-remove" aria-label={`Remove ${target.name}`} onClick={onRemove}>×</button> : null}
    </span>
  );
}

/** Choose a Stash tag, performer or studio by name, or create a new tag. */
function TargetPicker({ onPick, inputId }: { onPick: (t: Target) => void; inputId: string }) {
  const Select = PluginApi.libraries.ReactSelect.default;
  const [input, setInput] = React.useState("");
  const [found, setFound] = React.useState<Target[]>([]);
  const [top, setTop] = React.useState<Target[] | null>(null); // the most-used tags, shown before anything is typed
  React.useEffect(() => {
    if (!input.trim()) {
      setFound(top ?? []);
      return;
    }
    const timer = window.setTimeout(() => {
      runOperation<{ results: Target[] }>("stash_names_find", { q: input }).then((r) => setFound(r.results), () => setFound([]));
    }, 200);
    return () => window.clearTimeout(timer);
  }, [input, top]);
  function openMenu() {
    if (top) return;
    runOperation<{ results: Target[] }>("stash_names_find", { q: "" }).then((r) => setTop(r.results), () => setTop([]));
  }
  const text = input.trim();
  const exact = found.some((t) => t.kind === "tag" && t.name.toLowerCase() === text.toLowerCase());
  const options = [
    ...(["tag", "performer", "studio"] as TargetKind[]).map((kind) => ({
      label: text ? `${KIND_LABELS[kind]}s` : "Most used tags",
      options: found.filter((t) => t.kind === kind).map((t) => ({ value: `${t.kind}:${t.id}`, label: t.name, target: t })),
    })).filter((g) => g.options.length),
    ...(text && !exact ? [{ label: "New", options: [{ value: `new:${text}`, label: `Create tag "${text}"`, target: { kind: "tag", name: text, create: true } }] }] : []),
  ];
  return (
    <Select
      inputId={inputId}
      className="react-select imaglr-target-picker"
      classNamePrefix="react-select"
      value={null}
      options={options}
      inputValue={input}
      onInputChange={(v: string, meta: { action: string }) => meta.action === "input-change" && setInput(v)}
      onChange={(o: { target: Target } | null) => { if (o) onPick(o.target); setInput(""); }}
      onMenuOpen={openMenu}
      filterOption={() => true}
      placeholder="Add…"
      noOptionsMessage={() => (text ? "Nothing in Stash by that name" : top ? "Type a name" : "Loading…")}
      styles={{ option: (base: object) => ({ ...base, color: "#000" }), menuPortal: (base: object) => ({ ...base, zIndex: 1100 }) }}
      components={{ IndicatorSeparator: () => null, DropdownIndicator: () => null }}
      menuPlacement="auto"
      menuPortalTarget={document.body} // above the modal, not clipped by it
    />
  );
}

interface Props {
  post: ImaglrPost;
  blogId: number | null;
  onDone: (save: SaveState) => void;
  onCancel: () => void;
}

export function ReviewDialog({ post, blogId, onDone, onCancel }: Props) {
  const { Modal, Button, Form } = PluginApi.libraries.Bootstrap;
  const { LoadingIndicator } = PluginApi.components;
  const Toast = PluginApi.hooks.useToast();
  const [rows, setRows] = React.useState<Row[] | null>(null);
  const [extra, setExtra] = React.useState<Target[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    runOperation<{ rows: Omit<Row, "remember">[]; saved: StashRef[]; credit_id: string }>("save_review", { post_id: post.id, blog_id: blogId ?? undefined })
      .then((r) => {
        if (r.saved.length) {
          Toast.success("That post is already in your library.");
          onDone({ post_id: r.credit_id, status: "done", progress: 1, error: null, refs: r.saved });
          return;
        }
        setRows(r.rows.map((row) => ({ ...row, remember: row.source === "rule" })));
      }, (e: Error) => setError(e.message));
  }, [post.id, blogId]);

  /** A studio is one per item in Stash: choosing one takes it off everywhere else. */
  function withoutStudios(targets: Target[]) {
    return targets.filter((t) => t.kind !== "studio");
  }
  function add(index: number | null, target: Target) {
    const studio = target.kind === "studio";
    setRows((rs) => rs!.map((r, n) => {
      const targets = studio ? withoutStudios(r.targets) : r.targets;
      if (n !== index || targets.some((t) => t.kind === target.kind && t.id === target.id && t.name === target.name)) return { ...r, targets };
      return { ...r, targets: [...targets, target] };
    }));
    setExtra((e) => {
      const kept = studio ? withoutStudios(e) : e;
      return index === null && !kept.some((t) => t.kind === target.kind && t.id === target.id && t.name === target.name) ? [...kept, target] : kept;
    });
  }
  function removeAt(index: number, target: number) {
    setRows((rs) => rs!.map((r, n) => (n === index ? { ...r, targets: r.targets.filter((_, k) => k !== target) } : r)));
  }

  async function save() {
    if (!rows) return;
    setBusy(true);
    try {
      const r = await runOperation<{ save: SaveState }>("save_post", {
        post_id: post.id, blog_id: blogId ?? undefined,
        mapping: rows.map((row) => ({ tag: row.tag, targets: row.targets, remember: row.remember })), extra,
      });
      onDone(r.save);
    } catch (e) {
      Toast.error(e);
      setBusy(false);
    }
  }

  const who = post.original?.creator.name || post.creator.name;
  return (
    <Modal show onHide={onCancel} size="lg" className="imaglr-review">
      <Modal.Header closeButton>
        <Modal.Title>Save to your library</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <p className="small text-muted">
          {who ? `A post by @${who}. ` : ""}Choose what its imaglr tags become in Stash. Tags with nothing chosen are left out.
        </p>
        {error ? <div className="alert alert-warning">{error}</div> : null}
        {!rows && !error ? (LoadingIndicator ? <LoadingIndicator small /> : <p className="text-muted">Loading…</p>) : null}
        {rows ? (
          <div className="imaglr-review-rows">
            {rows.length === 0 ? <p className="text-muted">This post has no tags.</p> : null}
            {rows.map((row, n) => (
              <div key={row.tag} className="imaglr-review-row">
                <div className="imaglr-review-tag">
                  <strong>#{row.tag}</strong>
                  {WHY[row.source] && row.targets.length ? <span className="small text-muted"> · {WHY[row.source]}</span> : null}
                </div>
                <div className="imaglr-review-targets">
                  {row.targets.length
                    ? row.targets.map((t, k) => <TargetBadge key={`${t.kind}${t.id ?? t.name}`} target={t} onRemove={() => removeAt(n, k)} />)
                    : <span className="small text-muted">Left out</span>}
                </div>
                <div className="imaglr-review-edit">
                  <TargetPicker inputId={`imaglr-review-${n}`} onPick={(t) => add(n, t)} />
                  <Form.Check id={`imaglr-remember-${n}`} type="checkbox" label="Remember" checked={row.remember}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                      const remember = e.target.checked;
                      setRows((rs) => rs!.map((r, k) => (k === n ? { ...r, remember } : r)));
                    }} />
                </div>
              </div>
            ))}
            <div className="imaglr-review-row">
              <div className="imaglr-review-tag"><strong>Also add</strong></div>
              <div className="imaglr-review-targets">
                {extra.map((t, k) => <TargetBadge key={`${t.kind}${t.id ?? t.name}`} target={t}
                  onRemove={() => setExtra((e) => e.filter((_, i) => i !== k))} />)}
              </div>
              <div className="imaglr-review-edit"><TargetPicker inputId="imaglr-review-extra" onPick={(t) => add(null, t)} /></div>
            </div>
            <p className="small text-muted mb-0">
              Remembered choices apply to every post you save from now on. Change them in the plugin's Settings, under Import rules.
            </p>
          </div>
        ) : null}
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={onCancel} disabled={busy}>Cancel</Button>
        <Button variant="primary" onClick={save} disabled={!rows || busy}>{busy ? "Saving…" : "Save"}</Button>
      </Modal.Footer>
    </Modal>
  );
}

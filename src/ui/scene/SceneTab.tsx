// SPDX-License-Identifier: AGPL-3.0-only
// The "imaglr" tab on Stash's scene page: this scene's markers (queue them for imaglr with one tap) and
// "New clip", which reads start and end from Stash's own player so no second player is needed on a phone.
import React from "react";
import { baseUrl, runOperation } from "../api.ts";
import { fmtTime } from "../lib/format.ts";
import { ROUTE } from "../routes.ts";

interface MarkerRow {
  id: string;
  title: string;
  seconds: number;
  end_seconds: number | null;
  primary_tag: string | null;
  queued: boolean;
  sent: boolean;
  queue_is_primary: boolean;
  item_id: string | null;
  status: string | null;
  thumb: string | null;
}

interface SceneMarkers {
  markers: MarkerRow[];
  tags: { queue: { id: string; name: string }; done: { id: string; name: string } };
}

interface TagOption {
  id: string;
  name: string;
}

/** Current position of Stash's scene player (video.js renders a normal <video> inside #VideoJsPlayer). */
function playerTime(): number | null {
  const video = document.querySelector<HTMLVideoElement>("#VideoJsPlayer video, .video-js video");
  return video ? Math.round(video.currentTime * 10) / 10 : null;
}

function TagPicker({ value, placeholder, onChange }: {
  value: TagOption | null;
  placeholder: string;
  onChange: (tag: TagOption | null) => void;
}) {
  const { Form, Button } = PluginApi.libraries.Bootstrap;
  const [text, setText] = React.useState("");
  const [options, setOptions] = React.useState<TagOption[]>([]);

  React.useEffect(() => {
    if (!text.trim()) {
      setOptions([]);
      return;
    }
    const timer = window.setTimeout(() => {
      runOperation<{ tags: TagOption[] }>("tags_find", { q: text }).then((r) => setOptions(r.tags.slice(0, 8)), () => undefined);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [text]);

  if (value) {
    return (
      <div>
        <span className="imaglr-chip">
          {value.name}
          <button type="button" className="imaglr-chip-remove" aria-label="Use the default tag" onClick={() => onChange(null)}>×</button>
        </span>
      </div>
    );
  }
  return (
    <div>
      <Form.Control className="text-input" value={text} placeholder={placeholder}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setText(e.target.value)} />
      {options.length ? (
        <div className="imaglr-chips mt-1">
          {options.map((t) => (
            <Button key={t.id} variant="secondary" size="sm" onClick={() => { onChange(t); setText(""); }}>{t.name}</Button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function SceneImaglrTab({ sceneId, setTimestamp }: { sceneId: string; setTimestamp: (t: number) => void }) {
  const { Button, Form, Badge } = PluginApi.libraries.Bootstrap;
  const { Link } = PluginApi.libraries.ReactRouterDOM;
  const Toast = PluginApi.hooks.useToast();
  const [data, setData] = React.useState<SceneMarkers | null>(null);
  const [start, setStart] = React.useState<number | null>(null);
  const [end, setEnd] = React.useState<number | null>(null);
  const [title, setTitle] = React.useState("");
  const [primary, setPrimary] = React.useState<TagOption | null>(null);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(() => {
    runOperation<SceneMarkers>("scene_markers", { scene_id: sceneId }).then(setData, (e: Error) => Toast.error(e));
  }, [sceneId]);
  React.useEffect(load, [load]);

  function mark(which: "start" | "end") {
    const t = playerTime();
    if (t === null) {
      Toast.error("Start the video player first.");
      return;
    }
    (which === "start" ? setStart : setEnd)(t);
  }

  async function toggle(marker: MarkerRow) {
    try {
      await runOperation("marker_set_queued", { marker_id: marker.id, queued: !marker.queued });
      load();
    } catch (e) {
      Toast.error(e);
    }
  }

  async function create() {
    if (start === null || end === null) return;
    setBusy(true);
    try {
      await runOperation<{ item_id: string }>("marker_create", {
        scene_id: sceneId, seconds: start, end_seconds: end, title, primary_tag_id: primary?.id ?? null,
      });
      Toast.success("Clip created and added to imaglr.");
      setStart(null);
      setEnd(null);
      setTitle("");
      load();
    } catch (e) {
      Toast.error(e);
    } finally {
      setBusy(false);
    }
  }

  const valid = start !== null && end !== null && end - start >= 0.1;

  return (
    <div className="imaglr-scene-tab">
      <h6>New clip</h6>
      <p className="small text-muted">Play the video above, then set where the clip starts and ends.</p>
      <div className="imaglr-new-clip">
        <div>
          <Button variant="primary" onClick={() => mark("start")}>Set start</Button>
          <span className="imaglr-new-clip-time">{start === null ? "—" : fmtTime(start)}</span>
        </div>
        <div>
          <Button variant="primary" onClick={() => mark("end")}>Set end</Button>
          <span className="imaglr-new-clip-time">{end === null ? "—" : fmtTime(end)}</span>
        </div>
        {start !== null ? (
          <Button variant="link" className="p-0" onClick={() => setTimestamp(start)}>Jump to start</Button>
        ) : null}
      </div>
      {start !== null && end !== null && !valid ? <div className="small text-warning">The end must be after the start.</div> : null}
      <Form.Group className="mt-2">
        <Form.Label>Title <small className="text-muted">(optional)</small></Form.Label>
        <Form.Control className="text-input" value={title}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setTitle(e.target.value)} />
      </Form.Group>
      <Form.Group>
        <Form.Label>Marker tag <small className="text-muted">(optional)</small></Form.Label>
        <TagPicker value={primary} onChange={setPrimary}
          placeholder={`Search Stash tags, or leave empty to use "${data?.tags.queue.name ?? "imaglr"}"`} />
      </Form.Group>
      <Button variant="primary" disabled={!valid || busy} onClick={create}>
        {busy ? "Creating…" : "Create clip"}
      </Button>

      <h6 className="mt-4">Markers in this scene</h6>
      {!data ? <p className="text-muted">Loading…</p> : null}
      {data && data.markers.length === 0 ? <p className="text-muted">This scene has no markers yet.</p> : null}
      <ul className="imaglr-marker-list">
        {data?.markers.map((m) => (
          <li key={m.id} className="imaglr-marker">
            <button type="button" className="imaglr-marker-thumb" onClick={() => setTimestamp(m.seconds)} aria-label={`Jump to ${m.title}`}>
              {m.thumb ? <img src={baseUrl() + m.thumb} alt="" loading="lazy" /> : null}
            </button>
            <div className="imaglr-marker-body">
              <div className="imaglr-card-title">{m.title}</div>
              <div className="small text-muted">
                {fmtTime(m.seconds)}{m.end_seconds ? ` → ${fmtTime(m.end_seconds)}` : ""}
                {m.sent ? <> · <Badge variant="primary">Sent</Badge></> : null}
                {m.queued ? <> · <Badge variant="success">On imaglr page</Badge></> : null}
              </div>
            </div>
            <div className="imaglr-marker-actions">
              {m.queued && m.item_id ? (
                <Link to={`${ROUTE}?tab=clips&open=${m.item_id}`} className="btn btn-secondary">Open</Link>
              ) : null}
              <Button variant={m.queued ? "secondary" : "primary"} onClick={() => toggle(m)}
                disabled={m.queued && m.queue_is_primary}
                title={m.queued && m.queue_is_primary ? "It's this marker's main tag; change that in Stash first" : undefined}>
                {m.queued ? "Remove" : "Add to imaglr"}
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function patchScenePage() {
  PluginApi.patch.before("ScenePage.Tabs", (props: { children?: React.ReactNode }) => {
    const { Nav } = PluginApi.libraries.Bootstrap;
    return [{
      ...props,
      children: (
        <>
          {props.children}
          <Nav.Item>
            <Nav.Link eventKey="imaglr-panel">imaglr</Nav.Link>
          </Nav.Item>
        </>
      ),
    }];
  });
  PluginApi.patch.before("ScenePage.TabContent", (props: {
    children?: React.ReactNode;
    scene: { id: string };
    setTimestamp: (t: number) => void;
  }) => {
    const { Tab } = PluginApi.libraries.Bootstrap;
    return [{
      ...props,
      children: (
        <>
          {props.children}
          <Tab.Pane eventKey="imaglr-panel" mountOnEnter>
            <SceneImaglrTab sceneId={props.scene.id} setTimestamp={props.setTimestamp} />
          </Tab.Pane>
        </>
      ),
    }];
  });
}

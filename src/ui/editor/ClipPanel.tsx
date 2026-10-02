// SPDX-License-Identifier: AGPL-3.0-only
// Clip editor: plays the source from Stash, loops between in and out, crop overlay, mute, save still.
import React from "react";
import { gql } from "../api.ts";
import { clampTrim, pickStream, sameOrigin, type SceneStream, type VideoInfo } from "../lib/clip.ts";
import { ASPECTS, overlayRect } from "../lib/crop.ts";
import { describeGifEstimate, LONG_GIF_SECONDS } from "../lib/gif.ts";
import { fmtTime, parseTime } from "../lib/format.ts";
import type { Aspect } from "../lib/types.ts";

const SCENE_PLAYBACK = `query($id: ID!) { findScene(id: $id) {
  paths { stream screenshot } sceneStreams { url mime_type label }
  files { video_codec format width height duration } } }`;

const IMAGE_PLAYBACK = `query($id: ID!) { findImage(id: $id) {
  paths { image thumbnail }
  visual_files { ... on VideoFile { video_codec format width height duration } } } }`;

interface Playback {
  url: string;
  poster: string | null;
  duration: number | null;
}

async function loadPlayback(sceneId: string | null, imageId: string | null): Promise<Playback> {
  const canPlay = (mime: string) => document.createElement("video").canPlayType(mime) !== "";
  const origin = window.location.origin;
  if (sceneId) {
    const { findScene: s } = await gql<{
      findScene: { paths: { stream: string; screenshot: string | null }; sceneStreams: SceneStream[]; files: (VideoInfo & { duration: number })[] };
    }>(SCENE_PLAYBACK, { id: sceneId });
    const file = s.files[0] ?? {};
    return {
      url: sameOrigin(pickStream(s.paths.stream, s.sceneStreams, file, canPlay), origin),
      poster: s.paths.screenshot ? sameOrigin(s.paths.screenshot, origin) : null,
      duration: file.duration ?? null,
    };
  }
  const { findImage: i } = await gql<{
    findImage: { paths: { image: string; thumbnail: string | null }; visual_files: (VideoInfo & { duration?: number })[] };
  }>(IMAGE_PLAYBACK, { id: imageId });
  return {
    url: sameOrigin(i.paths.image, origin),
    poster: i.paths.thumbnail ? sameOrigin(i.paths.thumbnail, origin) : null,
    duration: i.visual_files[0]?.duration ?? null,
  };
}

export type ClipFormat = "video" | "gif";

export interface ClipState {
  inS: number;
  outS: number;
  mute: boolean;
  flip: boolean; // mirror left-to-right
  format: ClipFormat; // sent as a video, or as an animated GIF
  crop: { aspect: Aspect; position: number };
}

interface Props {
  sceneId: string | null;
  imageId: string | null;
  value: ClipState;
  disabled: boolean;
  gifTargetMb: number; // from the plugin's settings
  onChange: (value: ClipState) => void;
  onSaveStill: (t: number) => void;
}

function TimeRow({ label, value, disabled, onSet, onNudge, onType }: {
  label: string;
  value: number;
  disabled: boolean;
  onSet: () => void;
  onNudge: (delta: number) => void;
  onType: (seconds: number) => void;
}) {
  const { Button, Form } = PluginApi.libraries.Bootstrap;
  const [text, setText] = React.useState(fmtTime(value));
  React.useEffect(() => setText(fmtTime(value)), [value]);
  return (
    <div className="imaglr-time-row">
      <Form.Label className="imaglr-time-label">{label}</Form.Label>
      <Form.Control className="text-input imaglr-time-input" value={text} disabled={disabled} aria-label={`${label} time`}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setText(e.target.value)}
        onBlur={() => {
          const t = parseTime(text);
          if (t === null) setText(fmtTime(value));
          else onType(t);
        }} />
      <div className="imaglr-time-buttons">
        <Button variant="secondary" disabled={disabled} onClick={() => onNudge(-1)} aria-label={`${label} back 1 second`}>−1s</Button>
        <Button variant="secondary" disabled={disabled} onClick={() => onNudge(-0.1)} aria-label={`${label} back a tenth`}>−0.1</Button>
        <Button variant="primary" disabled={disabled} onClick={onSet}>Set here</Button>
        <Button variant="secondary" disabled={disabled} onClick={() => onNudge(0.1)} aria-label={`${label} forward a tenth`}>+0.1</Button>
        <Button variant="secondary" disabled={disabled} onClick={() => onNudge(1)} aria-label={`${label} forward 1 second`}>+1s</Button>
      </div>
    </div>
  );
}

export function ClipPanel({ sceneId, imageId, value, disabled, gifTargetMb, onChange, onSaveStill }: Props) {
  const { Button, ButtonGroup, Form } = PluginApi.libraries.Bootstrap;
  const video = React.useRef<HTMLVideoElement>(null);
  const box = React.useRef<HTMLDivElement>(null);
  const [playback, setPlayback] = React.useState<Playback | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [looping, setLooping] = React.useState(false);
  const [size, setSize] = React.useState({ w: 0, h: 0, vw: 0, vh: 0 });
  const valueRef = React.useRef(value);
  valueRef.current = value;

  React.useEffect(() => {
    loadPlayback(sceneId, imageId).then(setPlayback, (e: Error) => setError(e.message));
  }, [sceneId, imageId]);

  React.useEffect(() => {
    const onResize = () => measure();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  function measure() {
    const v = video.current;
    const b = box.current;
    if (v && b) setSize({ w: b.clientWidth, h: b.clientHeight, vw: v.videoWidth, vh: v.videoHeight });
  }

  const duration = playback?.duration ?? null;
  const now = () => video.current?.currentTime ?? 0;

  function trim(inS: number, outS: number, moved: "in" | "out") {
    const t = clampTrim(inS, outS, duration, moved);
    onChange({ ...value, inS: t.inS, outS: t.outS });
    if (video.current) video.current.currentTime = moved === "in" ? t.inS : Math.max(t.inS, t.outS - 1);
  }

  function playClip() {
    const v = video.current;
    if (!v) return;
    v.currentTime = value.inS;
    setLooping(true);
    v.play().catch(() => undefined); // autoplay refusals and interrupted loads are not errors
  }

  const rect = overlayRect(size.w, size.h, size.vw, size.vh, value.crop.aspect, value.crop.position);

  return (
    <div className="imaglr-clip">
      {error ? <div className="alert alert-danger">Can't play this video: {error}</div> : null}
      <div ref={box} className="imaglr-preview imaglr-video">
        {playback ? (
          <video ref={video} src={playback.url} poster={playback.poster ?? undefined} playsInline controls
            preload="metadata" muted={value.mute}
            onLoadedMetadata={() => {
              if (video.current) video.current.currentTime = value.inS;
              measure();
            }}
            onTimeUpdate={() => {
              const v = video.current;
              if (v && looping && v.currentTime >= valueRef.current.outS) v.currentTime = valueRef.current.inS;
            }}
            onPause={() => setLooping(false)} />
        ) : null}
        {rect.axis !== "none" ? (
          <div className="imaglr-crop" style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }} />
        ) : null}
      </div>

      <div className="imaglr-clip-summary">
        <span>
          {fmtTime(value.inS)} → {fmtTime(value.outS)} · <strong>{(value.outS - value.inS).toFixed(1)} s</strong>
        </span>
        <span className="imaglr-clip-actions">
          <Button variant="secondary" onClick={playClip}>Play clip</Button>
          <Button variant="secondary" disabled={disabled} onClick={() => onSaveStill(now())}>Save still</Button>
        </span>
      </div>

      <TimeRow label="In" value={value.inS} disabled={disabled}
        onSet={() => trim(now(), value.outS, "in")}
        onNudge={(d) => trim(value.inS + d, value.outS, "in")}
        onType={(t) => trim(t, value.outS, "in")} />
      <TimeRow label="Out" value={value.outS} disabled={disabled}
        onSet={() => trim(value.inS, now(), "out")}
        onNudge={(d) => trim(value.inS, value.outS + d, "out")}
        onType={(t) => trim(value.inS, t, "out")} />

      <Form.Group className="mt-2">
        <Form.Label>Crop</Form.Label>
        <div>
          <ButtonGroup className="imaglr-segmented">
            {(Object.keys(ASPECTS) as Aspect[]).map((a) => (
              <Button key={a} variant={value.crop.aspect === a ? "primary" : "secondary"} disabled={disabled}
                onClick={() => onChange({ ...value, crop: { ...value.crop, aspect: a } })}>
                {a === "original" ? "Original" : a}
              </Button>
            ))}
          </ButtonGroup>
        </div>
        {value.crop.aspect !== "original" ? (
          <Form.Control type="range" min={0} max={1} step={0.01} value={value.crop.position} disabled={disabled}
            aria-label="Crop position" className="mt-2"
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              onChange({ ...value, crop: { ...value.crop, position: Number(e.target.value) } })} />
        ) : null}
      </Form.Group>
      <Form.Group className="mt-2">
        <Form.Label>Format</Form.Label>
        <div>
          <ButtonGroup className="imaglr-segmented">
            {(["video", "gif"] as ClipFormat[]).map((f) => (
              <Button key={f} variant={value.format === f ? "primary" : "secondary"} disabled={disabled}
                onClick={() => onChange({ ...value, format: f })}>
                {f === "video" ? "Video" : "GIF"}
              </Button>
            ))}
          </ButtonGroup>
        </div>
        <div className="small text-muted mt-1">
          GIFs play straight away in feeds, with no tap, which tends to get more engagement. Videos are sharper,
          much smaller and can keep their sound.
        </div>
        {value.format === "gif" ? (
          <>
            <div className="small text-muted mt-1">
              This will be a GIF of {describeGifEstimate(value.outS - value.inS)}. GIFs over about {gifTargetMb} MB are slow to
              load, so the plugin will automatically lower the quality if it has to.
            </div>
            {value.outS - value.inS > LONG_GIF_SECONDS ? (
              <div className="small text-warning mt-1">
                Long GIFs may need lower frame-rates and resolutions. Clips below {LONG_GIF_SECONDS} seconds work best.
              </div>
            ) : null}
          </>
        ) : null}
      </Form.Group>
      {value.format === "gif" ? null : (
        <Form.Check id="imaglr-mute" type="switch" label="Remove sound" checked={value.mute} disabled={disabled}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange({ ...value, mute: e.target.checked })} />
      )}
      <Form.Check id="imaglr-flip" type="switch" label="Flip horizontally" checked={value.flip} disabled={disabled}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange({ ...value, flip: e.target.checked })} />
      {value.flip ? (
        <div className="small text-muted">The sent clip is mirrored left-to-right; the preview above isn't.</div>
      ) : null}
    </div>
  );
}

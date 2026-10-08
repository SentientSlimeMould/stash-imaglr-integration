// SPDX-License-Identifier: AGPL-3.0-only
// Clip editor: plays the source from Stash, loops between in and out, crop overlay, mute, save still.
import React from "react";
import { baseUrl, gql } from "../api.ts";
import { clampTrim, pickStream, sameOrigin, type SceneStream, type VideoInfo } from "../lib/clip.ts";
import { overlayRect } from "../lib/crop.ts";
import { CropControls } from "./CropControls.tsx";
import { Fold } from "./Fold.tsx";
import { describeGifEstimate, type GifLoop, gifSeconds, gifSizeChoicesFor, LONG_GIF_SECONDS } from "../lib/gif.ts";
import { CODEC_LABELS, type Codec, edgeLabel, outputEdge, sizeChoicesFor, videoEstimate } from "../lib/video.ts";
import { fmtTime, parseTime } from "../lib/format.ts";
import type { Crop } from "../lib/types.ts";

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
  codec: Codec; // videos: H.264 or H.265
  maxEdge: number | null; // videos: picture size as a long edge; null = as the source (up to 1080p)
  loop: GifLoop; // GIFs: forward, or forward then back
  gifWidth: number | null; // GIFs: picture width; null = the feed width (698 px)
  crop: Crop;
}

const LOOP_LABELS: Record<GifLoop, string> = { forward: "Forward", boomerang: "Boomerang" };


interface Props {
  itemId: string;
  sceneId: string | null;
  imageId: string | null;
  value: ClipState;
  disabled: boolean;
  gifTargetMb: number; // from the plugin's settings
  gifPreview: { url: string; note: string | null } | null; // the GIF as it would be sent, once made (null = none or stale)
  makingGif: boolean;
  onChange: (value: ClipState) => void;
  onSaveStill: (t: number) => void;
  onPreviewGif: () => void;
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

/** The Format section's header while it is collapsed: what the clip will be sent as, and its likely size. */
export function formatHeader(v: ClipState, estimate: { short: string; warn: boolean }, edge: number): { text: string; warn: boolean } {
  if (v.format === "gif") {
    const loop = v.loop === "boomerang" ? " · boomerang" : "";
    const size = v.gifWidth ? ` · ${v.gifWidth} px` : "";
    return { text: `GIF${loop}${size} · ${describeGifEstimate(v.outS - v.inS, v.loop, v.gifWidth)}`, warn: gifSeconds(v.outS - v.inS, v.loop) > LONG_GIF_SECONDS };
  }
  const parts = ["Video", CODEC_LABELS[v.codec], edgeLabel(edge), v.mute ? "no sound" : "", estimate.short];
  return { text: parts.filter(Boolean).join(" · "), warn: estimate.warn };
}

export function ClipPanel({ itemId, sceneId, imageId, value, disabled, gifTargetMb, gifPreview, makingGif, onChange, onSaveStill, onPreviewGif }: Props) {
  const { Button, ButtonGroup, Form } = PluginApi.libraries.Bootstrap;
  const video = React.useRef<HTMLVideoElement>(null);
  const box = React.useRef<HTMLDivElement>(null);
  const [playback, setPlayback] = React.useState<Playback | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [looping, setLooping] = React.useState(false);
  const [size, setSize] = React.useState({ w: 0, h: 0, vw: 0, vh: 0 });
  const [showGif, setShowGif] = React.useState(true); // when a GIF preview exists, show it rather than the video
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

  const sourceEdge = Math.max(size.vw, size.vh) || null;
  const sizeChoices = sizeChoicesFor(sourceEdge);
  const gifSizeChoices = gifSizeChoicesFor(size.vw || null);
  const estimate = videoEstimate(value.outS - value.inS, value.codec, outputEdge(sourceEdge, value.maxEdge), value.mute);
  const header = formatHeader(value, estimate, outputEdge(sourceEdge, value.maxEdge));
  const rect = overlayRect(size.w, size.h, size.vw, size.vh, value.crop.aspect, value.crop.position, value.crop.edges);

  return (
    <div className="imaglr-clip">
      {error ? <div className="alert alert-danger">Can't play this video: {error}</div> : null}
      <div ref={box} className="imaglr-preview imaglr-video">
        {gifPreview && showGif ? (
          <img className="imaglr-gif-preview" src={baseUrl() + gifPreview.url} alt="The GIF as it will be sent" />
        ) : null}
        {playback ? (
          <video ref={video} src={playback.url} poster={playback.poster ?? undefined} playsInline controls
            preload="metadata" muted={value.mute} style={gifPreview && showGif ? { display: "none" } : undefined}
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
        {rect.cropped && !(gifPreview && showGif) ? (
          <div className="imaglr-crop" style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }} />
        ) : null}
      </div>
      {value.format === "gif" ? (
        <div className="imaglr-gif-bar">
          {gifPreview ? (
            <span className="small text-muted">This is the GIF that will be sent: {gifPreview.note}</span>
          ) : (
            <span className="small text-muted">Make the GIF now to see exactly what will be sent.</span>
          )}
          <span className="imaglr-clip-actions">
            {gifPreview ? (
              <Button variant="secondary" onClick={() => setShowGif(!showGif)}>{showGif ? "Show video" : "Show GIF"}</Button>
            ) : null}
            <Button variant={gifPreview ? "secondary" : "primary"} disabled={disabled || makingGif} onClick={onPreviewGif}>
              {makingGif ? "Making the GIF…" : gifPreview ? "Make it again" : "Preview GIF"}
            </Button>
          </span>
        </div>
      ) : null}

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

      <CropControls crop={value.crop} disabled={disabled} itemId={itemId} onChange={(crop) => onChange({ ...value, crop })}
        flip={value.flip} onFlip={(flip) => onChange({ ...value, flip })} />
      <Fold id="format" label="Format" summary={header.text} tone={header.warn ? "warning" : "muted"}>
        <Form.Group className="mt-2">
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
            GIFs play automatically in feeds. Videos are higher quality, are quicker to load and have sound, but
            require the user to click play.
          </div>
        </Form.Group>
        {value.format === "gif" ? (
          <>
            <Form.Group className="mt-2 mb-2">
              <Form.Label>Loop</Form.Label>
              <div>
                <ButtonGroup className="imaglr-segmented">
                  {(Object.keys(LOOP_LABELS) as GifLoop[]).map((l) => (
                    <Button key={l} variant={value.loop === l ? "primary" : "secondary"} disabled={disabled}
                      onClick={() => onChange({ ...value, loop: l })}>
                      {LOOP_LABELS[l]}
                    </Button>
                  ))}
                </ButtonGroup>
              </div>
              <div className="small text-muted mt-1">
                A boomerang plays the clip forward then backward, so it loops without a jump. It doubles the frames.
              </div>
            </Form.Group>
            {gifSizeChoices.length > 1 ? (
              <Form.Group className="mb-2">
                <Form.Label>Picture size</Form.Label>
                <div>
                  <ButtonGroup className="imaglr-segmented">
                    {gifSizeChoices.map((o) => (
                      <Button key={o.label} variant={(value.gifWidth ?? null) === o.value ? "primary" : "secondary"} disabled={disabled}
                        onClick={() => onChange({ ...value, gifWidth: o.value })}>
                        {o.label}
                      </Button>
                    ))}
                  </ButtonGroup>
                </div>
                <div className="small text-muted mt-1">
                  Original is the feed's width, 698 px. A smaller picture makes a much smaller GIF.
                </div>
              </Form.Group>
            ) : null}
            <div className="small text-muted mt-1">
              This will be a GIF of {describeGifEstimate(value.outS - value.inS, value.loop, value.gifWidth)}. GIFs over about {gifTargetMb} MB are slow to
              load, so the plugin will automatically lower the quality if it has to.
            </div>
            {gifSeconds(value.outS - value.inS, value.loop) > LONG_GIF_SECONDS ? (
              <div className="small text-warning mt-1">
                Long GIFs may need lower frame-rates and resolutions. {value.loop === "boomerang" ? "A boomerang plays twice as long, so clips" : "Clips"} below {value.loop === "boomerang" ? LONG_GIF_SECONDS / 2 : LONG_GIF_SECONDS} seconds work best.
              </div>
            ) : null}
          </>
        ) : (
          <>
            <Form.Group className="mt-2 mb-2">
              <Form.Label>Codec</Form.Label>
              <div>
                <ButtonGroup className="imaglr-segmented">
                  {(Object.keys(CODEC_LABELS) as Codec[]).map((c) => (
                    <Button key={c} variant={value.codec === c ? "primary" : "secondary"} disabled={disabled}
                      onClick={() => onChange({ ...value, codec: c })}>
                      {CODEC_LABELS[c]}
                    </Button>
                  ))}
                </ButtonGroup>
              </div>
              <div className="small text-muted mt-1">
                H.265 is about 40 % smaller at the same quality and slower to encode. It plays in Safari, Chrome and
                Edge, but not every browser; H.264 plays everywhere.
              </div>
            </Form.Group>
            {sizeChoices.length > 1 ? (
              <Form.Group className="mb-2">
                <Form.Label>Picture size</Form.Label>
                <div>
                  <ButtonGroup className="imaglr-segmented">
                    {sizeChoices.map((o) => (
                      <Button key={o.label} variant={(value.maxEdge ?? null) === o.value ? "primary" : "secondary"} disabled={disabled}
                        onClick={() => onChange({ ...value, maxEdge: o.value })}>
                        {o.label}
                      </Button>
                    ))}
                  </ButtonGroup>
                </div>
                <div className="small text-muted mt-1">
                  Smaller pictures make smaller files and encode faster. Original keeps the source's size, up to 1080p.
                </div>
              </Form.Group>
            ) : null}
            <Form.Check id="imaglr-mute" type="switch" label="Remove sound" checked={value.mute} disabled={disabled}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange({ ...value, mute: e.target.checked })} />
            <div className={`small mt-1 ${estimate.warn ? "text-warning" : "text-muted"}`}>{estimate.text}</div>
          </>
        )}
      </Fold>
    </div>
  );
}

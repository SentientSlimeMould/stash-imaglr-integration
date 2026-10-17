// SPDX-License-Identifier: AGPL-3.0-only
// One imaglr post in the Discover feed: who posted it (and whose it was, for a reblog), its pictures and videos,
// caption, tags, and Save / Reblog. Pictures, GIFs and WebPs load straight from imaglr; Stash's page may only
// play video from Stash itself, so a video is fetched once through the plugin as it nears the screen, then
// plays muted while it is mostly in view, like a feed does. Built from Stash's own pieces (Bootstrap card,
// buttons, tag badges, Font Awesome icons); every control is thumb-sized.
import React from "react";
import { baseUrl, runOperation } from "../api.ts";
import { type ImaglrPost, mediaRatio, type PostMedia, relativeTime, SAVING, type SaveState, savedPath, shortCount } from "../lib/posts.ts";

// ---- videos: fetched a couple at a time, once each, and only one plays -----------------------------------
const previews = new Map<string, Promise<string>>();
const waiting: (() => void)[] = [];
let running = 0;
const MAX_FETCHES = 2;

function previewSrc(url: string): Promise<string> {
  let p = previews.get(url);
  if (!p) {
    p = new Promise<void>((go) => {
      if (running < MAX_FETCHES) {
        running += 1;
        go();
      } else waiting.push(() => { running += 1; go(); });
    })
      .then(() => runOperation<{ src: string }>("media_preview", { url }))
      .then((r) => baseUrl() + r.src)
      .finally(() => {
        running -= 1;
        waiting.shift()?.();
      });
    p.catch(() => previews.delete(url)); // a failure may be tried again later
    previews.set(url, p);
  }
  return p;
}

let playing: HTMLVideoElement | null = null;
let wantsSound = false; // once the viewer turns the sound on, the next videos start with it

/** Calls back with how much of the element is on screen (0..1), and whether it is within a screen of it. */
function useInView(ref: React.RefObject<HTMLElement>): { near: boolean; visible: number } {
  const [state, setState] = React.useState({ near: false, visible: 0 });
  React.useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const near = new IntersectionObserver(([e]) => setState((s) => (s.near || !e.isIntersecting ? s : { ...s, near: true })),
      { rootMargin: "100% 0px" });
    const seen = new IntersectionObserver(([e]) => setState((s) => ({ ...s, visible: e.intersectionRatio })),
      { threshold: [0, 0.25, 0.6, 0.9] });
    near.observe(el);
    seen.observe(el);
    return () => {
      near.disconnect();
      seen.disconnect();
    };
  }, [ref]);
  return state;
}

function VideoMedia({ media }: { media: PostMedia }) {
  const box = React.useRef<HTMLDivElement>(null);
  const video = React.useRef<HTMLVideoElement>(null);
  const { near, visible } = useInView(box);
  const [src, setSrc] = React.useState<string | null>(null);
  const [problem, setProblem] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!near || src || problem) return;
    let live = true;
    previewSrc(media.url).then((s) => live && setSrc(s), (e: Error) => live && setProblem(e.message));
    return () => {
      live = false;
    };
  }, [near, src, problem, media.url]);

  React.useEffect(() => {
    const v = video.current;
    if (!v || !src) return;
    if (visible >= 0.6) {
      if (playing && playing !== v) playing.pause();
      playing = v;
      v.muted = !wantsSound;
      v.play().catch(() => {
        v.muted = true; // the browser wants a tap before sound
        v.play().catch(() => undefined);
      });
    } else if (!v.paused) v.pause();
  }, [visible, src]);

  return (
    <div ref={box} className="imaglr-post-media" style={{ aspectRatio: String(mediaRatio(media)) }}>
      <video ref={video} src={src ?? undefined} poster={media.thumb ?? undefined} loop playsInline controls={!!src}
        preload="metadata" onVolumeChange={(e) => { wantsSound = !e.currentTarget.muted; }} />
      {!src && !problem ? <div className="imaglr-post-loading"><span className="spinner-border spinner-border-sm" /></div> : null}
      {problem ? <div className="imaglr-post-problem small">{problem}</div> : null}
    </div>
  );
}

function PictureMedia({ media }: { media: PostMedia }) {
  // imaglr's pictures load straight from its CDN. Only the development fake serves plain http on a Docker
  // address the browser can't reach, so its pictures come through the plugin like videos do.
  const direct = media.url.startsWith("https://");
  const box = React.useRef<HTMLDivElement>(null);
  const { near } = useInView(box);
  const [src, setSrc] = React.useState<string | null>(direct ? media.url : null);
  React.useEffect(() => {
    if (!direct && near && !src) previewSrc(media.url).then(setSrc, () => undefined);
  }, [direct, near, src, media.url]);
  return (
    <div ref={box} className="imaglr-post-media" style={{ aspectRatio: String(mediaRatio(media)) }}>
      {src ? <img src={src} alt="" loading="lazy" decoding="async" /> : null}
    </div>
  );
}

function Media({ media }: { media: PostMedia[] }) {
  const strip = React.useRef<HTMLDivElement>(null);
  const [index, setIndex] = React.useState(0);
  if (media.length === 0) return null;
  if (media.length === 1) return media[0].kind === "video" ? <VideoMedia media={media[0]} /> : <PictureMedia media={media[0]} />;
  return (
    <div className="imaglr-post-carousel">
      <div ref={strip} className="imaglr-post-strip"
        onScroll={(e) => setIndex(Math.round(e.currentTarget.scrollLeft / Math.max(1, e.currentTarget.clientWidth)))}>
        {media.map((m, n) => (
          <div key={n} className="imaglr-post-slide">
            {m.kind === "video" ? <VideoMedia media={m} /> : <PictureMedia media={m} />}
          </div>
        ))}
      </div>
      <span className="imaglr-post-counter badge badge-dark">{index + 1} / {media.length}</span>
    </div>
  );
}

function Avatar({ url, name }: { url: string | null; name: string }) {
  return url ? <img className="imaglr-avatar" src={url} alt="" loading="lazy" />
    : <span className="imaglr-avatar imaglr-avatar-letter" aria-hidden="true">{(name[0] ?? "?").toUpperCase()}</span>;
}

interface Props {
  post: ImaglrPost;
  save: SaveState | null; // the live state of a save of this post, if one was started
  onCreator: (name: string) => void;
  onTag: (tag: string) => void;
  onSave: (post: ImaglrPost) => void;
  onReblog: (post: ImaglrPost) => void;
}

export function PostCard({ post, save, onCreator, onTag, onSave, onReblog }: Props) {
  const { Button } = PluginApi.libraries.Bootstrap;
  const { Link } = PluginApi.libraries.ReactRouterDOM;
  const { Icon } = PluginApi.components;
  const fa = PluginApi.libraries.FontAwesomeSolid;
  const [expanded, setExpanded] = React.useState(false);
  const state = save ?? post.save;
  const refs = state?.status === "done" ? state.refs : post.saved;
  const inLibrary = savedPath(refs);
  const saving = !!state && SAVING.includes(state.status);
  const longCaption = post.summary.length > 160 || post.summary.split("\n").length > 3;

  return (
    <article className="card imaglr-post">
      <header className="imaglr-post-head">
        <Avatar url={post.creator.avatar} name={post.creator.name} />
        <div className="imaglr-post-who">
          <button type="button" className="btn btn-link imaglr-post-name" onClick={() => onCreator(post.creator.name)}>
            {post.creator.name || "someone"}
          </button>
          {post.original ? (
            <span className="small text-muted">
              <Icon icon={fa.faRetweet} />{" "}
              <button type="button" className="btn btn-link imaglr-post-original" onClick={() => onCreator(post.original!.creator.name)}>
                {post.original.creator.name || "the original"}
              </button>
            </span>
          ) : null}
        </div>
        <span className="small text-muted imaglr-post-time">{relativeTime(post.created_at)}</span>
        {post.url ? (
          <a className="btn btn-link imaglr-post-open" href={post.url} target="_blank" rel="noopener noreferrer" title="Open on imaglr">
            <Icon icon={fa.faExternalLinkAlt} />
          </a>
        ) : null}
      </header>

      <Media media={post.media} />

      <div className="card-body imaglr-post-body">
        {post.summary ? (
          <p className={`imaglr-post-caption${expanded || !longCaption ? "" : " imaglr-post-caption-short"}`}>
            {post.summary}
          </p>
        ) : null}
        {longCaption && !expanded ? (
          <button type="button" className="btn btn-link p-0 small" onClick={() => setExpanded(true)}>more</button>
        ) : null}
        {post.tags.length ? (
          <div className="imaglr-post-tags">
            {post.tags.map((t) => (
              <button key={t} type="button" className="tag-item badge badge-secondary" onClick={() => onTag(t)}>#{t}</button>
            ))}
          </div>
        ) : null}
        <div className="imaglr-post-actions">
          <span className="small text-muted imaglr-post-notes">
            <Icon icon={fa.faHeart} /> {shortCount(post.notes.likes)}
            <span className="ml-3"><Icon icon={fa.faRetweet} /> {shortCount(post.notes.reposts)}</span>
          </span>
          <Button variant="secondary" onClick={() => onReblog(post)}>
            <Icon icon={fa.faRetweet} /> Reblog
          </Button>
          {post.media.length === 0 ? null : inLibrary ? (
            <Link className="btn btn-secondary imaglr-post-saved" to={`/${inLibrary}`}>
              <Icon icon={fa.faCheck} /> In your library
            </Link>
          ) : saving ? (
            <Button variant="primary" disabled>
              <span className="spinner-border spinner-border-sm" />{" "}
              {state!.status === "scanning" ? "Adding to Stash…" : `Saving… ${Math.round(state!.progress * 100)}%`}
            </Button>
          ) : (
            <Button variant="primary" onClick={() => onSave(post)}>
              <Icon icon={fa.faDownload} /> {state?.status === "failed" ? "Try again" : "Save"}
            </Button>
          )}
        </div>
        {state?.status === "failed" && state.error ? <div className="small text-warning mt-2">{state.error}</div> : null}
      </div>
    </article>
  );
}

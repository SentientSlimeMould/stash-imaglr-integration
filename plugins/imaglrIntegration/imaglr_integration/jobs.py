# SPDX-License-Identifier: AGPL-3.0-only
"""Sending a post: runs as a Stash plugin task (one at a time, in Stash's job queue).

prepare every file that isn't prepared yet → POST /drafts → optionally queue or publish the draft →
swap the queue tag for the sent tag in Stash. The outcome is recorded on the item, because Stash
reports every plugin task as FINISHED whatever happened.
"""

from __future__ import annotations

import os
import shutil
import time
import traceback
from typing import Any

from . import blogs, log, services
from .cleanup import cleanup_prepared
from . import items as repo
from . import settings as plugin_settings
from .context import Context
from .db import now_iso
from .imaglr import ErrorClass, ImaglrError, UploadCancelled
from .media.ffmpeg_run import Cancelled, FfmpegError
from .media.image_inspect import ImageFormatError, inspect_image
from .media.image_plan import plan_image
from .media.image_process import ImageTooLarge, process_image
from .media.metadata_strip import StripError
from .media.naming import slugify
from .media import ffmpeg_cmd as fc
from .media.probe import probe
from .media.video_export import (GifTooLarge, UnsupportedMedia, VideoSettings, detect_edges, export_clip, export_gif,
                                 gif_to_mp4, grab_frame, hevc_available)
from .stash import HttpStream, LocalFile, StashError, api
from .stash.paths import image_source, scene_source
from .tags.caption import caption_to_html
from .tags.pipeline import MAX_TAGS, dropped_tags

IMAGE_LIMIT = 40 * 1024 * 1024  # imaglr: 40 MB per image
# imaglr's documentation says 500 MB per video and roughly 900 MB per request, but its API sits behind an edge
# that refuses any request body over 100 MiB with a bare 413 (measured 2026-10-08: 97 MiB accepted, 101 MiB
# refused, two 55 MB files in one post refused). The post's files have to fit this together.
REQUEST_LIMIT = 100 * 1024 * 1024
VIDEO_LIMIT = REQUEST_LIMIT
MIN_VIDEO_BYTES = 2 * 1024 * 1024  # below this share of the request a video isn't worth encoding
SAFETY = 0.95  # stay under the limits
MAX_RATE_LIMIT_WAIT = 120  # longer waits fail the item with a retry button instead of blocking Stash's queue

FOLLOW_UP_LABELS = {"queue": "adding it to your imaglr queue", "publish": "publishing it"}


class JobFailed(Exception):
    """What went wrong, in words for the user. The detail is shown on the card, stored, and logged, so it
    is redacted here once (ffmpeg errors quote the input URL, for example)."""

    def __init__(self, code: str, detail: str, status: str = "failed"):
        detail = log.redact(detail)
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def prepared_dir(ctx: Context, item_id: str) -> str:
    return os.path.join(ctx.data_dir, "prepared", item_id)


def media_tools(ctx: Context) -> tuple[str, str]:
    status = ctx.stash.gql("{ systemStatus { ffmpegPath ffprobePath } }")["systemStatus"]
    if not status["ffmpegPath"] or not status["ffprobePath"]:
        raise JobFailed("ffmpeg_missing", "Stash can't find ffmpeg/ffprobe. Check Settings → System in Stash.")
    return status["ffmpegPath"], status["ffprobePath"]


def choose_blog(ctx: Context, item: dict[str, Any]) -> dict[str, Any]:
    all_blogs = blogs.list_blogs(ctx.db)
    if not all_blogs:
        raise JobFailed("no_blog", "Add an imaglr blog in the plugin's settings first.", status="ready")
    blog = blogs.get_blog(ctx.db, item["blog_id"]) if item["blog_id"] else None
    if blog is None:
        if len(all_blogs) > 1:
            raise JobFailed("choose_blog", "Choose which blog to send this to.", status="ready")
        blog = all_blogs[0]
    if blog["paused_reason"]:
        raise JobFailed(blog["paused_reason"], pause_message(blog), status="ready")
    return blog


def pause_message(blog: dict[str, Any]) -> str:
    name = blog["name"] or "this blog"
    if blog["paused_reason"] == "premium_required":
        return f"imaglr says {name} isn't a paid supporter right now, and the API needs one. Sending resumes when it is."
    return f"imaglr has suspended {name}."


# ---- preparing files ------------------------------------------------------------------------


def _cancel_check(ctx: Context, item_id: str):
    def should_cancel() -> bool:
        row = ctx.db.fetchone("SELECT cancel_requested FROM items WHERE id=?", (item_id,))
        return bool(row and row["cancel_requested"])

    return should_cancel


def prepare_image(ctx: Context, member: dict[str, Any], tools: tuple[str, str], should_cancel) -> dict[str, Any]:
    image = api.find_image(ctx.stash, member["stash_image_id"])
    if image is None:
        raise JobFailed("source_deleted", f"{member['source_title']} no longer exists in Stash.")
    out_dir = _fresh_dir(ctx, member["id"])
    source = image_source(image)
    if source is None:
        raise JobFailed("source_missing", f"Stash has no file for {member['source_title']}.")
    downloaded = None
    if isinstance(source, HttpStream):
        downloaded = os.path.join(out_dir, "source")
        api.download(ctx.stash, source.url, downloaded)
    try:
        return _process_picture(ctx, member, downloaded or source.path, out_dir, tools, should_cancel)
    finally:
        if downloaded and os.path.exists(downloaded):
            os.remove(downloaded)


def prepare_still(ctx: Context, member: dict[str, Any], tools: tuple[str, str], should_cancel) -> dict[str, Any]:
    frame = member["source_path"]
    if not frame or not os.path.isfile(frame):
        raise JobFailed("source_missing", "This still's frame is missing. Save the still again from its clip.")
    out_dir = os.path.join(prepared_dir(ctx, member["id"]), "out")
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)
    return _process_picture(ctx, member, frame, out_dir, tools, should_cancel)


def _fresh_dir(ctx: Context, item_id: str) -> str:
    out_dir = prepared_dir(ctx, item_id)
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)
    return out_dir


def _process_picture(ctx, member, path, out_dir, tools, should_cancel) -> dict[str, Any]:
    """Strip, orient, crop and convert one still picture (an image or a frame grab)."""
    ffmpeg, ffprobe = tools
    crop = member["crop"] or {}
    aspect = crop.get("aspect") or "original"
    position = float(crop.get("position", 0.5))
    edges = fc.clean_edges(crop.get("edges"))
    base_name = slugify(os.path.splitext(member["source_title"])[0] or f"image-{member['id']}")
    try:
        info = inspect_image(path, ffprobe)
        plan = plan_image(info, None if aspect == "original" else aspect, int(IMAGE_LIMIT * SAFETY), edges)
        if plan.action == "to_video":
            result = gif_to_mp4(path, out_dir, base_name, VideoSettings(ffmpeg, ffprobe), aspect=aspect,
                                position=position, should_cancel=should_cancel, edges=edges)
            output, size, mime = result.path, result.bytes, "video/mp4"
        else:
            result = process_image(path, out_dir, base_name, plan, info, aspect, position,
                                   int(IMAGE_LIMIT * SAFETY), ffmpeg=ffmpeg, should_cancel=should_cancel,
                                   crop_edges=edges)
            output, size, mime = result.path, result.bytes, result.mime
    except ImageTooLarge as e:
        raise JobFailed("file_too_large", f"{member['source_title']}: {e}") from None
    except (ImageFormatError, StripError, UnsupportedMedia) as e:
        raise JobFailed("unsupported_image", f"{member['source_title']}: {e}") from None
    except FfmpegError as e:
        raise JobFailed("ffmpeg_failed", f"{member['source_title']}: {e}") from None
    return repo.update_item(ctx.db, member["id"], output_path=output, output_bytes=size, output_mime=mime,
                            error_code=None, error_detail=None)  # type: ignore[return-value]


def clip_source(ctx: Context, item: dict[str, Any]) -> tuple[str, dict[str, str] | None]:
    """The video a clip (or a still's clip) is cut from: a readable local path, else Stash's stream URL
    with auth headers for ffmpeg."""
    if item["stash_marker_id"]:
        marker = api.find_marker(ctx.stash, item["stash_marker_id"])
        if marker is None or marker.scene is None:
            raise JobFailed("source_deleted", f"The marker for {item['source_title']} no longer exists in Stash.")
        source = scene_source(marker.scene)
    elif item["stash_image_id"]:
        image = api.find_image(ctx.stash, item["stash_image_id"])
        if image is None:
            raise JobFailed("source_deleted", f"{item['source_title']} no longer exists in Stash.")
        source = image_source(image)
    else:
        raise JobFailed("source_missing", "This clip has no source in Stash.")
    if isinstance(source, LocalFile):
        return source.path, None
    if isinstance(source, HttpStream):
        return source.url, api.auth_headers(ctx.stash)
    raise JobFailed("source_missing", f"Stash has no video file for {item['source_title']}.")


GIF_FALLBACK_NOTE = "Sent as a video - the GIF would have been over imaglr's limit."


def prepare_clip(ctx: Context, member: dict[str, Any], tools: tuple[str, str], should_cancel, progress,
                 bitrate_scale: float | None = None, previous_bytes: int | None = None,
                 config: plugin_settings.Settings | None = None, gif_fallback: bool = False,
                 max_bytes: int | None = None) -> dict[str, Any]:
    """Export one clip. `max_bytes` is this video's share of the request (see video_budget); the GIF path has
    its own target."""
    ffmpeg, ffprobe = tools
    config = config or plugin_settings.Settings()
    src, headers = clip_source(ctx, member)
    crop = member["crop"] or {}
    edges = fc.clean_edges(crop.get("edges"))
    if member["format"] == "gif":
        try:
            result = export_gif(
                src, _fresh_dir(ctx, member["id"]), title=member["source_title"] or "clip",
                in_s=float(member["in_s"] or 0), out_s=float(member["out_s"] or 0),
                settings=VideoSettings(ffmpeg, ffprobe), headers=headers,
                target_bytes=int(config.gif_target_mb * 1024 * 1024),
                limit_bytes=int(plugin_settings.GIF_HARD_LIMIT_MB * 1024 * 1024 * SAFETY),
                aspect=crop.get("aspect") or "original", position=float(crop.get("position", 0.5)),
                flip=bool(member["flip"]), progress_cb=progress, should_cancel=should_cancel, edges=edges,
            )
        except GifTooLarge as e:
            if not gif_fallback:
                raise JobFailed(
                    "gif_too_large",
                    f"This GIF is too big even at its smallest ({e.size / 1048576:.0f} MB; the limit is "
                    f"{plugin_settings.GIF_HARD_LIMIT_MB}). Trim it to about {e.fit_seconds:.0f} seconds, or send it as a video.",
                ) from None
            log.info(f"{member['source_title']}: GIF would be {e.size / 1048576:.0f} MB; sending as a video instead")
            member = repo.update_item(ctx.db, member["id"], format="video") or member  # type: ignore[assignment]
            return prepare_clip(ctx, member, tools, should_cancel, progress, config=config,
                                max_bytes=max_bytes) | {"gif_fallback": True}
        except (UnsupportedMedia, ValueError) as e:
            raise JobFailed("unsupported_video", f"{member['source_title']}: {e}") from None
        except FfmpegError as e:
            raise JobFailed("ffmpeg_failed", f"{member['source_title']}: {e}") from None
        return repo.update_item(ctx.db, member["id"], output_path=result.path, output_bytes=result.bytes,
                                output_mime="image/gif", output_note=result.note, hdr_warning=False,
                                error_code=None, error_detail=None)  # type: ignore[return-value]
    codec = member["codec"] or "h264"
    if codec == "hevc" and not hevc_available(ffmpeg):
        raise JobFailed("no_hevc", f"{member['source_title']}: this Stash's ffmpeg has no H.265 encoder. "
                        "Choose H.264 for the clip.")
    video_settings = VideoSettings(ffmpeg, ffprobe, codec=codec, max_long_edge=min(1920, member["max_edge"] or 1920))
    if max_bytes:
        video_settings.max_video_mb = max_bytes / 1048576
    try:
        result = export_clip(
            src, _fresh_dir(ctx, member["id"]), title=member["source_title"] or "clip",
            in_s=float(member["in_s"] or 0), out_s=float(member["out_s"] or 0),
            settings=video_settings, headers=headers,
            aspect=crop.get("aspect") or "original", position=float(crop.get("position", 0.5)),
            mute=bool(member["mute"]), flip=bool(member["flip"]), progress_cb=progress, should_cancel=should_cancel,
            bitrate_scale=bitrate_scale, previous_bytes=previous_bytes, edges=edges,
        )
    except (UnsupportedMedia, ValueError) as e:
        raise JobFailed("unsupported_video", f"{member['source_title']}: {e}") from None
    except FfmpegError as e:
        raise JobFailed("ffmpeg_failed", f"{member['source_title']}: {e}") from None
    if result.hdr:
        log.warning(f"{member['source_title']}: HDR source; colours may look washed out (tone mapping isn't supported)")
    return repo.update_item(ctx.db, member["id"], output_path=result.path, output_bytes=result.bytes,
                            output_mime="video/mp4", output_note=result.note, hdr_warning=result.hdr,
                            error_code=None, error_detail=None)  # type: ignore[return-value]


def picture_file(ctx: Context, item: dict[str, Any], work_dir: str) -> str:
    """A local copy of a picture item's file (an image's, or a still's grabbed frame), fetched from Stash when
    it only streams it (e.g. inside a zip)."""
    if item["kind"] == "still":
        if not item["source_path"] or not os.path.isfile(item["source_path"]):
            raise JobFailed("source_missing", "This still's frame is missing. Save the still again from its clip.")
        return item["source_path"]
    image = api.find_image(ctx.stash, item["stash_image_id"])
    if image is None:
        raise JobFailed("source_deleted", f"{item['source_title']} no longer exists in Stash.")
    source = image_source(image)
    if isinstance(source, LocalFile):
        return source.path
    if isinstance(source, HttpStream):
        os.makedirs(work_dir, exist_ok=True)
        path = os.path.join(work_dir, "source")
        api.download(ctx.stash, source.url, path)
        return path
    raise JobFailed("source_missing", f"Stash has no file for {item['source_title']}.")


def detect_borders(ctx: Context, item: dict[str, Any]) -> dict[str, float]:
    """Edge trims that cut the black borders off this item's picture: a clip is sampled across its range from
    its video; a picture is looked at once, from a local copy."""
    ffmpeg, ffprobe = media_tools(ctx)
    work_dir = os.path.join(prepared_dir(ctx, item["id"]), "detect")
    try:
        if item["kind"] == "clip":
            src, headers = clip_source(ctx, item)
            w, h = probe(ffprobe, src, headers).display_size
            a, b = float(item["in_s"] or 0), float(item["out_s"] or 0)
            times = [a + (b - a) * f for f in (0.1, 0.35, 0.6, 0.85)] if b > a else [a]
        else:
            src, headers = picture_file(ctx, item, work_dir), None
            w, h = inspect_image(src, ffprobe).display_size
            times = [0.0]
        if not w or not h:
            raise JobFailed("unsupported_video", "Couldn't read the picture's size.")
        return detect_edges(ffmpeg, src, w, h, times, headers)
    except (FfmpegError, ImageFormatError) as e:
        log.warning(f"border detection failed for {item['id']}: {e}")
        raise JobFailed("ffmpeg_failed", "Couldn't look for borders: Stash's ffmpeg can't read this picture. "
                        "Set the trims by hand instead.") from None
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def grab_still(ctx: Context, clip: dict[str, Any], t: float, still_id: str) -> str:
    """Grab the frame at t seconds from the clip's source video into the still's folder."""
    ffmpeg, _ = media_tools(ctx)
    src, headers = clip_source(ctx, clip)
    out_dir = prepared_dir(ctx, still_id)
    os.makedirs(out_dir, exist_ok=True)
    try:
        return grab_frame(src, t, os.path.join(out_dir, "frame.jpg"), ffmpeg, headers=headers)
    except FfmpegError as e:
        raise JobFailed("ffmpeg_failed", f"Couldn't grab that frame: {e}") from None


def _is_prepared(member: dict[str, Any], max_bytes: int | None = None) -> bool:
    path = member["output_path"]
    if member["kind"] == "clip":  # a prepared GIF is no use when the clip is to go as a video, and vice versa
        wanted = "image/gif" if member["format"] == "gif" else "video/mp4"
        if member["output_mime"] != wanted:
            return False
    if max_bytes and (member["output_bytes"] or 0) > max_bytes:  # e.g. prepared for a bigger limit than now
        return False
    return bool(path and os.path.isfile(path) and os.path.getsize(path) == member["output_bytes"])


def _is_video(member: dict[str, Any]) -> bool:
    return member["kind"] == "clip" and member["format"] != "gif"


def video_budget(members: list[dict[str, Any]]) -> int:
    """Bytes each video in the post may take: the request limit less what the other files take, shared equally
    among the videos. Raises when that is too little to be worth encoding."""
    videos = [m for m in members if _is_video(m)]
    if not videos:
        return VIDEO_LIMIT
    others = sum(m["output_bytes"] or 0 for m in members if not _is_video(m))
    share = int((REQUEST_LIMIT * SAFETY - others) / len(videos))
    if share < MIN_VIDEO_BYTES:
        raise JobFailed("file_too_large", f"Together these files are over imaglr's {REQUEST_LIMIT // 1048576} MB "
                        "per post. Split the post.")
    return share


# ---- sending --------------------------------------------------------------------------------


def _wait(seconds: float, should_cancel) -> None:
    """Sleep in short slices so Stop is noticed during rate-limit and retry waits."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if should_cancel():
            raise Cancelled()
        time.sleep(min(0.5, max(0.0, end - time.monotonic())))


def _upload(client, files, tags, body, progress, should_cancel) -> Any:
    """POST /drafts, riding out short rate limits and brief imaglr/network hiccups. Never retries once the
    whole body went out: imaglr may have saved the draft although the reply was lost."""
    for attempt in range(4):
        try:
            return client.create_draft(files, tags=tags, body_html=body, progress_cb=progress, should_cancel=should_cancel)
        except UploadCancelled:
            raise Cancelled() from None
        except ImaglrError as e:
            if e.klass is ErrorClass.RATE_LIMITED and e.retry_after and e.retry_after <= MAX_RATE_LIMIT_WAIT and attempt < 3:
                log.info(f"imaglr rate limit: waiting {e.retry_after:.0f} s")
                _wait(e.retry_after, should_cancel)
                continue
            if e.klass is ErrorClass.TRANSIENT and attempt < 2 and not e.body_sent:
                log.info(f"imaglr {e.code}: retrying in {5 * 4 ** attempt} s")
                _wait(5 * 4**attempt, should_cancel)
                continue
            if e.body_sent:
                e.detail = (e.detail or e.code) + " (after the upload completed; check your imaglr drafts before sending again)"
            raise


def _upload_error(ctx: Context, blog: dict[str, Any], e: ImaglrError) -> JobFailed:
    klass = e.klass
    detail = e.detail or e.code
    if klass is ErrorClass.AUTH:
        return JobFailed(e.code, f"imaglr no longer accepts the key for {blog['name']}. Replace it in settings.")
    if klass is ErrorClass.SCOPE:
        return JobFailed(e.code, f"The key for {blog['name']} lacks the 'manage' permission. Make a new key with read + manage.")
    if klass is ErrorClass.PREMIUM:
        blogs.set_paused(ctx.db, blog["id"], e.code)
        return JobFailed(e.code, pause_message(blogs.get_blog(ctx.db, blog["id"])), status="ready")  # type: ignore[arg-type]
    if klass is ErrorClass.INVALID and e.field:
        return JobFailed(e.code, f"imaglr rejected the {e.field}: {detail}")
    if klass is ErrorClass.RATE_LIMITED:
        wait = f" Try again after {int(e.retry_after // 60) + 1} minutes." if e.retry_after else ""
        which = "daily posting" if "daily" in e.code else "hourly"
        return JobFailed(e.code, f"imaglr's {which} limit is used up.{wait}")
    return JobFailed(e.code, detail)


def _shrink_videos(ctx: Context, members: list[dict[str, Any]], should_cancel) -> bool:
    """imaglr rejected the upload as too large: re-encode each clip once at 90 % of the target bitrate.
    Returns False when there is nothing left to shrink (images are already sized under imaglr's limit)."""
    clips = [n for n, m in enumerate(members) if _is_video(m) and not m["size_guard_retried"]]
    if not clips:
        return False
    tools = media_tools(ctx)
    budget = video_budget(members)
    for n in clips:
        repo.update_item(ctx.db, members[n]["id"], size_guard_retried=True)
        members[n] = prepare_clip(ctx, members[n], tools, should_cancel, lambda f: None, bitrate_scale=0.9,
                                  previous_bytes=members[n]["output_bytes"], max_bytes=budget)
    return True


def _follow_up(client, action: str, draft_id: str) -> dict[str, Any]:
    return client.publish_draft(draft_id) if action == "publish" else client.queue_draft(draft_id)


def run_send(ctx: Context, item_id: str, action: str | None = None, gif_fallback: bool = False,
             format_override: str | None = None) -> None:
    """The task. `action` is what the send operation decided (Send all downgrades publish to draft without
    changing the item's own setting); otherwise the item's or the blog's default applies. With `gif_fallback`
    a GIF that can't be made small enough is sent as a video instead of failing; `format_override` sends every
    clip in the post as that format this time, without changing the clips' own settings."""
    item = repo.get_item(ctx.db, item_id)
    if item is None or item["status"] != "exporting":  # only what send/send_all just queued; never twice
        return
    should_cancel = _cancel_check(ctx, item_id)
    members = repo.set_members(ctx.db, item_id) if item["kind"] == "set" else [item]
    if format_override in ("video", "gif"):
        members = [{**m, "format": format_override} if m["kind"] == "clip" else m for m in members]
    try:
        if not members:
            raise JobFailed("post_empty", "This post has no files.")
        blog = choose_blog(ctx, item)
        if action not in blogs.ACTIONS:
            action = blogs.resolve_action(blog, item["action"])
        try:
            config = plugin_settings.load(ctx.stash)
        except plugin_settings.SettingsError as e:
            raise JobFailed("settings", str(e), status="ready") from None
        queue_tag, done_tag = api.workflow_tags(ctx.stash, config.queue_tag, config.done_tag)
        # Automatic tags follow Stash and the tag rules until edited: bring them up to date now (the send
        # operation already marked the item busy, hence force).
        item = services.refresh_item_tags(ctx.stash, ctx.db, config, item, force=True)
        tags = list(item["tags"])[:MAX_TAGS]

        # 1. prepare (0-40 %). Images, stills and GIFs first: their sizes decide how much of the request the
        # videos may take between them.
        repo.update_item(ctx.db, item_id, status="exporting", progress=0, error_code=None, error_detail=None)
        tools = None
        fell_back: list[str] = []  # clips sent as video because their GIF wouldn't fit
        order = [n for n, m in enumerate(members) if not _is_video(m)] + [n for n, m in enumerate(members) if _is_video(m)]
        budget: int | None = None
        for done, n in enumerate(order):
            member = members[n]
            if should_cancel():
                raise Cancelled()
            if _is_video(member) and budget is None:
                budget = video_budget(members)
            if not _is_prepared(member, budget if _is_video(member) else None):
                tools = tools or media_tools(ctx)
                if member["kind"] == "clip":
                    def clip_progress(fraction: float, done: int = done) -> None:
                        log.progress(0.4 * (done + fraction) / len(members))

                    members[n] = prepare_clip(ctx, member, tools, should_cancel, clip_progress, config=config,
                                              gif_fallback=gif_fallback, max_bytes=budget)
                    if members[n].pop("gif_fallback", False):
                        fell_back.append(members[n]["id"])
                        budget = None  # a GIF became a video: the shares change for the videos still to come
                elif member["kind"] == "still":
                    members[n] = prepare_still(ctx, member, tools, should_cancel)
                else:
                    members[n] = prepare_image(ctx, member, tools, should_cancel)
            log.progress(0.4 * (done + 1) / len(members))
            repo.update_item(ctx.db, item_id, progress=0.4 * (done + 1) / len(members))

        files = [(m["output_path"], m["output_mime"]) for m in members]
        for m in members:
            limit = VIDEO_LIMIT if (m["output_mime"] or "").startswith("video/") else IMAGE_LIMIT
            if m["output_bytes"] > limit:
                raise JobFailed("file_too_large", f"{m['source_title']} is over imaglr's {limit // 1048576} MB upload limit.")
        if sum(m["output_bytes"] for m in members) > REQUEST_LIMIT:
            raise JobFailed("file_too_large", f"Together these files are over imaglr's {REQUEST_LIMIT // 1048576} MB "
                            "per post. Split the post.")

        # 2. upload (40-95 %)
        repo.update_item(ctx.db, item_id, status="sending")
        client = ctx.imaglr(blog)

        def progress(fraction: float) -> None:
            log.progress(0.4 + 0.55 * fraction)

        try:
            draft = _upload(client, files, tags, caption_to_html(item["caption"]), progress, should_cancel)
        except ImaglrError as e:
            if e.klass is not ErrorClass.TOO_LARGE or not _shrink_videos(ctx, members, should_cancel):
                raise _upload_error(ctx, blog, e) from None
            log.info(f"imaglr said too large; re-encoded smaller, uploading {item_id} again")
            files = [(m["output_path"], m["output_mime"]) for m in members]
            try:
                draft = _upload(client, files, tags, caption_to_html(item["caption"]), progress, should_cancel)
            except ImaglrError as e2:
                raise _upload_error(ctx, blog, e2) from None
    except Cancelled:
        repo.update_item(ctx.db, item_id, status="ready" if all(map(_is_prepared, members)) else "pending",
                         progress=0, cancel_requested=False, error_code="cancelled", error_detail="Stopped.")
        return
    except JobFailed as e:
        log.warning(f"send {item_id}: {e.code}: {e.detail}")
        repo.update_item(ctx.db, item_id, status=e.status, progress=0, error_code=e.code, error_detail=e.detail)
        return
    except StashError as e:
        repo.update_item(ctx.db, item_id, status="failed", progress=0, error_code="stash_error",
                         error_detail=log.redact(str(e)))
        return
    except Exception as e:  # a bug or a broken environment: say so on the card instead of staying "busy" forever
        log.error(f"send {item_id}: unexpected {type(e).__name__}: {e}\n{traceback.format_exc()}")
        repo.update_item(ctx.db, item_id, status="failed", progress=0, error_code="unexpected",
                         error_detail=log.redact(f"Something went wrong: {type(e).__name__}: {e}")[:500])
        return

    # 3. the draft exists: from here on nothing may re-upload it
    record = dict(status="sent", progress=1.0, draft_id=draft.id, post_url=draft.url, sent_as="draft",
                  sent_at=now_iso(), blog_id=blog["id"], dropped_tags=dropped_tags(tags, draft.tags) if draft.tags else [],
                  followup_failed=False, error_code=None, error_detail=None, cancel_requested=False,
                  tags_pending=True)
    try:
        if action != "draft":
            try:
                _follow_up(client, action, draft.id)
                record["sent_as"] = action
            except ImaglrError as e:
                record.update(followup_failed=True, error_code=e.code,
                              error_detail=f"Saved as a draft, but {FOLLOW_UP_LABELS[action]} failed: {e.detail or e.code}")
        if fell_back:
            record["output_note"] = GIF_FALLBACK_NOTE
        repo.update_item(ctx.db, item_id, **record)
        for m in members if item["kind"] == "set" else []:
            repo.update_item(ctx.db, m["id"], status="sent", draft_id=draft.id, post_url=draft.url,
                             sent_as=record["sent_as"], sent_at=record["sent_at"], blog_id=blog["id"], tags_pending=True)
        repo.bump_used_tags(ctx.db, tags)
        log.progress(0.97)

        # 4. Stash: swap the queue tag for the sent tag on every source. A source whose swap fails keeps
        # tags_pending, so the queue retries it later instead of treating the source as newly queued.
        failed = swap_source_tags(ctx, members, queue_tag, done_tag)
        if not failed:
            repo.update_item(ctx.db, item_id, tags_pending=False)
        else:
            message = "Stash's tags couldn't be updated for: " + ", ".join(failed)
            log.warning(f"sent {item_id}: {message}")
            if record["followup_failed"]:
                repo.update_item(ctx.db, item_id, error_detail=log.redact(f"{record['error_detail']} Also, {message}")[:500])
            else:
                repo.update_item(ctx.db, item_id, error_code="tag_swap_failed", error_detail=log.redact("Sent, but " + message)[:500])
        log.info(f"sent {item_id} to {blog['name']} as {record['sent_as']} (draft {draft.id})")
        cleanup_prepared(ctx.db, os.path.join(ctx.data_dir, "prepared"), config.prepared_retention_days)
    except Exception as e:  # the draft is on imaglr: the item is sent, whatever else broke
        log.error(f"send {item_id}: after the draft was saved: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        record.update(error_code="unexpected",
                      error_detail=log.redact(f"Saved as a draft, but then: {type(e).__name__}: {e}")[:500])
        repo.update_item(ctx.db, item_id, **record)
    log.progress(1.0)


def swap_source_tags(ctx: Context, members: list[dict[str, Any]], queue_tag, done_tag) -> list[str]:
    """Queue tag -> sent tag on each member's Stash source; clears tags_pending per member. Returns the
    members that failed, as text for the user."""
    failed = []
    for m in members:
        try:
            if m["stash_marker_id"]:
                marker = api.find_marker(ctx.stash, m["stash_marker_id"])
                if marker:
                    api.marker_swap_tags(ctx.stash, marker, queue_tag, done_tag)
            elif m["stash_image_id"]:
                api.image_swap_tags(ctx.stash, m["stash_image_id"], queue_tag, done_tag)
            repo.update_item(ctx.db, m["id"], tags_pending=False)
        except StashError as e:
            failed.append(f"{m['source_title']} ({e})")
    return failed


def retry_follow_up(ctx: Context, item: dict[str, Any]) -> dict[str, Any]:
    """Queue or publish a draft that was saved but whose follow-up call failed. Never re-uploads."""
    blog = blogs.get_blog(ctx.db, item["blog_id"]) if item["blog_id"] else None
    if blog is None or not item["draft_id"]:
        raise JobFailed("cannot_retry", "This draft's blog is no longer set up.")
    action = blogs.resolve_action(blog, item["action"])
    try:
        _follow_up(ctx.imaglr(blog), action, item["draft_id"])
    except ImaglrError as e:
        raise JobFailed(e.code, f"{FOLLOW_UP_LABELS.get(action, action)} failed again: {e.detail or e.code}") from None
    still_pending = item["tags_pending"]  # keep saying so if the Stash tags are still wrong
    return repo.update_item(ctx.db, item["id"], sent_as=action, followup_failed=False,
                            error_code="tag_swap_failed" if still_pending else None,
                            error_detail="Sent, but Stash's tags couldn't be updated." if still_pending else None)  # type: ignore[return-value]

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
from typing import Any

from . import blogs, log
from . import items as repo
from . import settings as plugin_settings
from .context import Context
from .db import now_iso
from .imaglr import ErrorClass, ImaglrError
from .media.ffmpeg_run import Cancelled, FfmpegError
from .media.image_inspect import ImageFormatError, inspect_image
from .media.image_plan import plan_image
from .media.image_process import ImageTooLarge, process_image
from .media.metadata_strip import StripError
from .media.naming import slugify
from .media.video_export import UnsupportedMedia, VideoSettings, export_clip, gif_to_mp4, grab_frame
from .stash import HttpStream, LocalFile, StashError, api
from .stash.paths import image_source, scene_source
from .tags.caption import caption_to_html
from .tags.pipeline import dropped_tags

IMAGE_LIMIT = 40 * 1024 * 1024  # imaglr: 40 MB per image
VIDEO_LIMIT = 500 * 1024 * 1024  # imaglr: 500 MB per video
REQUEST_LIMIT = 900 * 1024 * 1024  # imaglr: "one request may total roughly 900 MB"
SAFETY = 0.95  # stay under the limits
MAX_RATE_LIMIT_WAIT = 120  # longer waits fail the item with a retry button instead of blocking Stash's queue

FOLLOW_UP_LABELS = {"queue": "adding it to your imaglr queue", "publish": "publishing it"}


class JobFailed(Exception):
    def __init__(self, code: str, detail: str, status: str = "failed"):
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
    base_name = slugify(os.path.splitext(member["source_title"])[0] or f"image-{member['id']}")
    try:
        info = inspect_image(path, ffprobe)
        plan = plan_image(info, None if aspect == "original" else aspect, int(IMAGE_LIMIT * SAFETY))
        if plan.action == "to_video":
            result = gif_to_mp4(path, out_dir, base_name, VideoSettings(ffmpeg, ffprobe), aspect=aspect,
                                position=position, should_cancel=should_cancel)
            output, size, mime = result.path, result.bytes, "video/mp4"
        else:
            result = process_image(path, out_dir, base_name, plan, info, aspect, position,
                                   int(IMAGE_LIMIT * SAFETY), ffmpeg=ffmpeg, should_cancel=should_cancel)
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


def prepare_clip(ctx: Context, member: dict[str, Any], tools: tuple[str, str], should_cancel, progress) -> dict[str, Any]:
    ffmpeg, ffprobe = tools
    src, headers = clip_source(ctx, member)
    crop = member["crop"] or {}
    try:
        result = export_clip(
            src, _fresh_dir(ctx, member["id"]), title=member["source_title"] or "clip",
            in_s=float(member["in_s"] or 0), out_s=float(member["out_s"] or 0),
            settings=VideoSettings(ffmpeg, ffprobe), headers=headers,
            aspect=crop.get("aspect") or "original", position=float(crop.get("position", 0.5)),
            mute=bool(member["mute"]), progress_cb=progress, should_cancel=should_cancel,
        )
    except (UnsupportedMedia, ValueError) as e:
        raise JobFailed("unsupported_video", f"{member['source_title']}: {e}") from None
    except FfmpegError as e:
        raise JobFailed("ffmpeg_failed", f"{member['source_title']}: {e}") from None
    if result.hdr:
        log.warning(f"{member['source_title']}: HDR source; colours may look washed out (tone mapping isn't supported)")
    return repo.update_item(ctx.db, member["id"], output_path=result.path, output_bytes=result.bytes,
                            output_mime="video/mp4", hdr_warning=result.hdr, error_code=None,
                            error_detail=None)  # type: ignore[return-value]


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


def _is_prepared(member: dict[str, Any]) -> bool:
    path = member["output_path"]
    return bool(path and os.path.isfile(path) and os.path.getsize(path) == member["output_bytes"])


# ---- sending --------------------------------------------------------------------------------


def _upload(client, files, tags, body, progress) -> Any:
    """POST /drafts, riding out short rate limits and brief imaglr/network hiccups."""
    for attempt in range(4):
        try:
            return client.create_draft(files, tags=tags, body_html=body, progress_cb=progress)
        except ImaglrError as e:
            if e.klass is ErrorClass.RATE_LIMITED and e.retry_after and e.retry_after <= MAX_RATE_LIMIT_WAIT and attempt < 3:
                log.info(f"imaglr rate limit: waiting {e.retry_after:.0f} s")
                time.sleep(e.retry_after)
                continue
            if e.klass is ErrorClass.TRANSIENT and attempt < 2:
                log.info(f"imaglr {e.code}: retrying in {5 * 4 ** attempt} s")
                time.sleep(5 * 4**attempt)
                continue
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
        return JobFailed(e.code, f"imaglr's hourly limit is used up.{wait}")
    return JobFailed(e.code, detail)


def _follow_up(client, action: str, draft_id: str) -> dict[str, Any]:
    return client.publish_draft(draft_id) if action == "publish" else client.queue_draft(draft_id)


def run_send(ctx: Context, item_id: str) -> None:
    item = repo.get_item(ctx.db, item_id)
    if item is None or item["status"] == "sent":
        return
    should_cancel = _cancel_check(ctx, item_id)
    members = repo.set_members(ctx.db, item_id) if item["kind"] == "set" else [item]
    try:
        if not members:
            raise JobFailed("post_empty", "This post has no files.")
        blog = choose_blog(ctx, item)
        action = blogs.resolve_action(blog, item["action"])
        try:
            config = plugin_settings.load(ctx.stash)
        except plugin_settings.SettingsError as e:
            raise JobFailed("settings", str(e), status="ready") from None
        queue_tag, done_tag = api.workflow_tags(ctx.stash, config.queue_tag, config.done_tag)

        # 1. prepare (0-40 %)
        repo.update_item(ctx.db, item_id, status="exporting", progress=0, error_code=None, error_detail=None)
        tools = None
        for n, member in enumerate(members):
            if should_cancel():
                raise Cancelled()
            if not _is_prepared(member):
                tools = tools or media_tools(ctx)
                if member["kind"] == "clip":
                    def clip_progress(fraction: float, n: int = n) -> None:
                        log.progress(0.4 * (n + fraction) / len(members))

                    members[n] = prepare_clip(ctx, member, tools, should_cancel, clip_progress)
                elif member["kind"] == "still":
                    members[n] = prepare_still(ctx, member, tools, should_cancel)
                else:
                    members[n] = prepare_image(ctx, member, tools, should_cancel)
            log.progress(0.4 * (n + 1) / len(members))
            repo.update_item(ctx.db, item_id, progress=0.4 * (n + 1) / len(members))

        files = [(m["output_path"], m["output_mime"]) for m in members]
        for m in members:
            limit = VIDEO_LIMIT if (m["output_mime"] or "").startswith("video/") else IMAGE_LIMIT
            if m["output_bytes"] > limit:
                raise JobFailed("file_too_large", f"{m['source_title']} is over imaglr's size limit.")
        if sum(m["output_bytes"] for m in members) > REQUEST_LIMIT:
            raise JobFailed("file_too_large", "Together these files are over imaglr's ~900 MB per post.")

        # 2. upload (40-95 %)
        repo.update_item(ctx.db, item_id, status="sending")
        client = ctx.imaglr(blog)
        tags = list(item["tags"])[:30]

        def progress(fraction: float) -> None:
            log.progress(0.4 + 0.55 * fraction)

        try:
            draft = _upload(client, files, tags, caption_to_html(item["caption"]), progress)
        except ImaglrError as e:
            raise _upload_error(ctx, blog, e) from None
    except Cancelled:
        repo.update_item(ctx.db, item_id, status="ready" if all(map(_is_prepared, members)) else "pending",
                         progress=0, cancel_requested=False, error_code="cancelled", error_detail="Stopped.")
        return
    except JobFailed as e:
        log.warning(f"send {item_id}: {e.code}: {e.detail}")
        repo.update_item(ctx.db, item_id, status=e.status, progress=0, error_code=e.code, error_detail=e.detail)
        return
    except StashError as e:
        repo.update_item(ctx.db, item_id, status="failed", progress=0, error_code="stash_error", error_detail=str(e))
        return

    # 3. the draft exists: from here on nothing may re-upload it
    record = dict(status="sent", progress=1.0, draft_id=draft.id, post_url=draft.url, sent_as="draft",
                  sent_at=now_iso(), blog_id=blog["id"], dropped_tags=dropped_tags(tags, draft.tags) if draft.tags else [],
                  followup_failed=False, error_code=None, error_detail=None, cancel_requested=False)
    if action != "draft":
        try:
            _follow_up(client, action, draft.id)
            record["sent_as"] = action
        except ImaglrError as e:
            record.update(followup_failed=True, error_code=e.code,
                          error_detail=f"Saved as a draft, but {FOLLOW_UP_LABELS[action]} failed: {e.detail or e.code}")
    repo.update_item(ctx.db, item_id, **record)
    for m in members if item["kind"] == "set" else []:
        repo.update_item(ctx.db, m["id"], status="sent", draft_id=draft.id, post_url=draft.url,
                         sent_as=record["sent_as"], sent_at=record["sent_at"], blog_id=blog["id"])
    repo.bump_used_tags(ctx.db, tags)
    log.progress(0.97)

    # 4. Stash: swap the queue tag for the sent tag on every source
    failed = []
    for m in members:
        try:
            if m["stash_marker_id"]:
                marker = api.find_marker(ctx.stash, m["stash_marker_id"])
                if marker:
                    api.marker_swap_tags(ctx.stash, marker, queue_tag, done_tag)
            elif m["stash_image_id"]:
                api.image_swap_tags(ctx.stash, m["stash_image_id"], queue_tag, done_tag)
        except StashError as e:
            failed.append(f"{m['source_title']} ({e})")
    if failed and not record["followup_failed"]:
        repo.update_item(ctx.db, item_id, error_code="tag_swap_failed",
                         error_detail="Sent, but Stash's tags couldn't be updated for: " + ", ".join(failed)[:500])
    log.info(f"sent {item_id} to {blog['name']} as {record['sent_as']} (draft {draft.id})")
    log.progress(1.0)


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
    return repo.update_item(ctx.db, item["id"], sent_as=action, followup_failed=False, error_code=None,
                            error_detail=None)  # type: ignore[return-value]

# SPDX-License-Identifier: AGPL-3.0-only
"""Browsing imaglr from Stash and saving the posts the user chooses into their library (with imaglr's
permission: personal use, chosen posts only, credit kept; see saving.py for where the credit lives).

Operations answer the browse view: a page of the feed, the user's likes, a tag or a creator; a video to preview
(imaglr's CDN can't be played from Stash's page directly, so it is fetched once into the plugin's own folder);
the save folder; starting a save; reblogging. Saving itself is two queued Stash tasks with a scan between them:
`task_save` downloads the files and queues a scan of just those files, then queues `task_save_apply`, which
Stash's one-at-a-time queue runs after the scan and which writes the credit onto what the scan made.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from . import blogs, log, saving
from .context import Context, UserError, imaglr_base_override
from .db import now_iso
from .imaglr import DisallowedEndpoint, ErrorClass, ImaglrError, MediaRefused, classify, fetch_media, media_url_ok
from .settings import PLUGIN_ID, Settings
from .settings import load as load_settings
from .stash import StashError, library

SOURCES = ("feed", "likes", "tag", "creator")
PREVIEW_DIR = "_browse"  # under data/prepared, so Stash serves it from the plugin's assets
PREVIEW_MAX_BYTES = 200 * 1024 * 1024  # bigger videos are opened on imaglr instead
PREVIEW_CACHE_BYTES = 1024 * 1024 * 1024  # the previews kept, newest first
IN_PROGRESS = ("queued", "downloading", "scanning")
RUN_TASK = """
mutation($id: ID!, $description: String, $args: Map) {
  runPluginTask(plugin_id: $id, description: $description, args_map: $args)
}
"""


class SaveFailed(Exception):
    """A save that can't go on; the message is shown on the post."""


# ---- shared helpers ------------------------------------------------------------------------------------
def _settings(ctx: Context) -> Settings:
    return load_settings(ctx.stash)


def _require_enabled(ctx: Context) -> Settings:
    config = _settings(ctx)
    if not config.save_enabled:
        raise UserError("Browsing imaglr is switched off. Turn it on in Settings → Plugins → Imaglr Integration.")
    return config


def _blog(ctx: Context) -> dict[str, Any]:
    """The blog whose key reads imaglr: the one asked for, else the first that works."""
    if ctx.args.get("blog_id") is not None:
        blog = blogs.get_blog(ctx.db, ctx.arg("blog_id", int))
        if blog is None:
            raise UserError("That blog has been removed. Choose another.")
        return blog
    found = [b for b in blogs.list_blogs(ctx.db) if b["ok"]] or blogs.list_blogs(ctx.db)
    if not found:
        raise UserError("Add your imaglr blog in the plugin's settings first.")
    return found[0]


def _extra_host() -> str | None:
    return imaglr_base_override()  # development only: the fake imaglr serves its media from its own address


def _imaglr_message(e: ImaglrError, blog: dict[str, Any] | None = None, doing: str = "read imaglr") -> str:
    name = (blog or {}).get("name") or "this blog"
    kind = classify(e.code)
    if e.code in ("post_not_found", "profile_not_found", "not_found"):
        return "That isn't available on imaglr: it may be private or deleted."
    if e.code == "likes_are_private":
        return "That profile doesn't share its likes."
    if kind is ErrorClass.AUTH:
        return f"imaglr didn't accept {name}'s key. Check it in the plugin's settings."
    if kind is ErrorClass.SCOPE:
        return f"{name}'s key isn't allowed to {doing}. Give the key that permission on imaglr."
    if kind is ErrorClass.PREMIUM:
        return f"imaglr has paused {name}'s key (premium or account status)."
    if kind is ErrorClass.RATE_LIMITED:
        return "imaglr asks to slow down for a moment. Try again in a minute."
    if kind is ErrorClass.TRANSIENT:
        return "imaglr isn't answering right now. Try again shortly."
    return f"imaglr said {e.code}" + (f": {e.detail}" if e.detail else ".")


def _save_view(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"post_id": row["post_id"], "status": row["status"], "progress": row["progress"], "error": row["error"],
            "refs": json.loads(row["refs"] or "[]")}


def _save_row(ctx: Context, post_id: str) -> dict[str, Any] | None:
    return ctx.db.fetchone("SELECT * FROM saves WHERE post_id=?", (post_id,))


def _save_update(ctx: Context, post_id: str, **changes: Any) -> None:
    changes["updated_at"] = now_iso()
    sets = ", ".join(f"{k}=?" for k in changes)
    ctx.db.execute(f"UPDATE saves SET {sets} WHERE post_id=?", (*changes.values(), post_id))


def _annotate(ctx: Context, posts: list[dict[str, Any]]) -> None:
    """Mark each post with what the user's Stash already holds of it, and any save under way."""
    ids = [saving.credit(p)["id"] for p in posts]
    refs = library.saved_refs(ctx.stash, ids)
    rows = {r["post_id"]: r for r in ctx.db.fetchall(
        f"SELECT * FROM saves WHERE post_id IN ({','.join('?' * len(ids))})", tuple(ids))} if ids else {}
    for post, credited in zip(posts, ids):
        post["credit_id"] = credited
        post["saved"] = refs.get(credited, [])
        row = rows.get(credited)
        post["save"] = _save_view(row) if row and (row["status"] in IN_PROGRESS or row["status"] == "failed") else None


# ---- browsing ------------------------------------------------------------------------------------------
def op_browse(ctx: Context) -> dict[str, Any]:
    """One page of posts: the feed, the user's likes, a tag or a creator. `next` is the link a previous page
    returned. A creator's first page also carries their profile."""
    _require_enabled(ctx)
    blog = _blog(ctx)
    source = ctx.arg("source")
    if source not in SOURCES:
        raise UserError("Unknown list.")
    nxt = ctx.args.get("next") or None
    client = ctx.imaglr(blog)
    profile = None
    try:
        if source == "feed":
            page = client.feed(nxt)
        elif source == "likes":
            page = client.likes(nxt)
        elif source == "tag":
            tag = (ctx.arg("tag") or "").strip().lstrip("#")
            if not tag:
                raise UserError("Which tag?")
            page = client.tagged(tag, nxt)
        else:
            name = (ctx.arg("name") or "").strip().lstrip("@")
            if not name:
                raise UserError("Which creator?")
            if not nxt:
                profile = saving.creator_view(client.profile(name))
            page = client.profile_posts(name, nxt)
    except ImaglrError as e:
        raise UserError(_imaglr_message(e, blog)) from None
    except DisallowedEndpoint:
        raise UserError("That link can't be followed. Start the list again.") from None
    posts = [saving.normalize_post(p) for p in page.posts]
    _annotate(ctx, posts)
    return {"posts": posts, "next": page.next, "profile": profile,
            "blog": {"id": blog["id"], "name": blog["name"]}}


def op_post_find(ctx: Context) -> dict[str, Any]:
    """One post, from its imaglr link or id (Save a link)."""
    _require_enabled(ctx)
    blog = _blog(ctx)
    text = (ctx.arg("link") or "").strip()
    post_id = text.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
    if not post_id.isdigit():
        raise UserError("That isn't an imaglr post link. It looks like https://imaglr.com/post/12345.")
    try:
        post = saving.normalize_post(ctx.imaglr(blog).post(post_id))
    except ImaglrError as e:
        raise UserError(_imaglr_message(e, blog)) from None
    _annotate(ctx, [post])
    return {"post": post}


def _prune_previews(folder: str, keep: str) -> None:
    """Keep the preview folder under its size, dropping the least recently played first."""
    try:
        entries = [(e.stat().st_mtime, e.stat().st_size, e.path) for e in os.scandir(folder) if e.is_file()]
    except OSError:
        return
    total = sum(size for _, size, _ in entries)
    for mtime, size, path in sorted(entries):
        if total <= PREVIEW_CACHE_BYTES:
            break
        if os.path.basename(path) == keep:
            continue
        try:
            os.remove(path)
            total -= size
        except OSError:
            pass


def op_media_preview(ctx: Context) -> dict[str, Any]:
    """A post's video, fetched once into the plugin's folder so Stash's page may play it; returns its address
    (relative to Stash's base). Pictures don't need this: the page shows them straight from imaglr."""
    _require_enabled(ctx)
    url = ctx.arg("url")
    if not media_url_ok(url, _extra_host()):
        raise UserError("That file isn't on imaglr.")
    folder = os.path.join(ctx.data_dir, "prepared", PREVIEW_DIR)
    os.makedirs(folder, exist_ok=True)
    name = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24] + saving.extension({"url": url, "kind": "video", "mime": None})
    path = os.path.join(folder, name)
    if os.path.exists(path):
        os.utime(path)
    else:
        try:
            fetch_media(url, path, ctx.version, max_bytes=PREVIEW_MAX_BYTES, extra_host=_extra_host())
        except MediaRefused:
            raise UserError("This video is too big to preview here. Open it on imaglr.") from None
        except ImaglrError as e:
            raise UserError(_imaglr_message(e)) from None
        _prune_previews(folder, name)
    return {"src": f"plugin/{PLUGIN_ID}/assets/prepared/{PREVIEW_DIR}/{name}"}


# ---- the save folder -----------------------------------------------------------------------------------
def op_save_setup(ctx: Context) -> dict[str, Any]:
    """Whether browsing is on, where saves go, and the libraries a save folder may be in."""
    config = _settings(ctx)
    libs, _ = library.libraries(ctx.stash)
    lib = saving.library_for(config.save_folder, libs) if config.save_folder else None
    return {"enabled": config.save_enabled, "autoplay": config.browse_autoplay, "folder": config.save_folder or None,
            "folder_ok": lib is not None,
            "libraries": [{"path": l["path"], "videos": not l.get("excludeVideo"), "images": not l.get("excludeImage")}
                          for l in libs]}


def op_save_folder_set(ctx: Context) -> dict[str, Any]:
    """Choose where saved posts go: a folder inside one of Stash's libraries that takes pictures and videos."""
    folder = (ctx.arg("folder") or "").strip()
    libs, _ = library.libraries(ctx.stash)
    lib = saving.library_for(folder, libs) if folder else None
    if lib is None:
        raise UserError("Choose a folder inside one of your Stash libraries, so Stash finds what you save.")
    if lib.get("excludeVideo") or lib.get("excludeImage"):
        raise UserError("That library skips videos or pictures. Choose one that takes both.")
    library.set_plugin_config(ctx.stash, PLUGIN_ID, {"browseImaglrSaveFolder": folder})
    return op_save_setup(ctx)


# ---- saving --------------------------------------------------------------------------------------------
def op_save_post(ctx: Context) -> dict[str, Any]:
    """Start saving one post: read it from imaglr again (it may have changed or gone private), then queue the
    download as a Stash task. A reblog is saved as the original post, with the original's tags, caption and date
    when imaglr still shows it. A post already in the library is not saved twice."""
    config = _require_enabled(ctx)
    if not config.save_folder:
        raise UserError("Choose where saved posts go first.")
    libs, _ = library.libraries(ctx.stash)
    if saving.library_for(config.save_folder, libs) is None:
        raise UserError("The save folder isn't inside a Stash library any more. Choose it again.")
    blog = _blog(ctx)
    client = ctx.imaglr(blog)
    try:
        post = saving.normalize_post(client.post(ctx.arg("post_id")))
    except ImaglrError as e:
        raise UserError(_imaglr_message(e, blog)) from None
    if post["original"]:
        try:
            original = saving.normalize_post(client.post(post["original"]["id"]))
            if original["media"]:
                post = original
        except ImaglrError:
            pass  # the original is no longer visible: keep the reblog's copy, still credited to the original
    if not post["media"]:
        raise UserError("This post has no pictures or videos to save.")
    credited = saving.credit(post)["id"]
    existing = library.saved_refs(ctx.stash, [credited])[credited]
    if existing:
        return {"save": {"post_id": credited, "status": "done", "progress": 1, "error": None, "refs": existing}}
    row = _save_row(ctx, credited)
    if row and row["status"] in IN_PROGRESS:
        return {"save": _save_view(row)}
    now = now_iso()
    ctx.db.execute("INSERT OR REPLACE INTO saves(post_id, status, progress, blog_id, post, files, refs, error, created_at, updated_at) "
                   "VALUES(?, 'queued', 0, ?, ?, '[]', '[]', NULL, ?, ?)", (credited, blog["id"], json.dumps(post), now, now))
    who = saving.credit(post)["creator"]["name"] or "imaglr"
    try:
        job = ctx.stash.gql(RUN_TASK, {"id": PLUGIN_ID, "description": f"imaglr: saving a post by @{who}",
                                       "args": {"mode": "task_save", "post_id": credited}})["runPluginTask"]
    except StashError:
        _save_update(ctx, credited, status="failed", error="Stash couldn't start the save.")
        raise
    _save_update(ctx, credited, stash_job_id=str(job))
    return {"save": _save_view(_save_row(ctx, credited))}


def op_save_status(ctx: Context) -> dict[str, Any]:
    """Saves under way, and those that ended in the last few minutes (so the page can show them finish)."""
    recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")
    rows = ctx.db.fetchall("SELECT * FROM saves WHERE status IN ('queued','downloading','scanning') "
                           "OR updated_at >= ? ORDER BY updated_at DESC LIMIT 200", (recent,))
    return {"saves": [_save_view(r) for r in rows]}


def task_save(ctx: Context) -> None:
    """Download a post's files into the save folder, then queue a scan of them and the task that credits them."""
    post_id = ctx.arg("post_id")
    row = _save_row(ctx, post_id)
    if row is None or row["status"] != "queued":
        return None
    written: list[str] = []
    try:
        folder = _settings(ctx).save_folder
        if not folder:
            raise SaveFailed("Choose where saved posts go first.")
        post = json.loads(row["post"])
        plan = saving.file_plan(folder, post)
        _save_update(ctx, post_id, status="downloading", progress=0)
        for n, (media, path) in enumerate(plan):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if not os.path.exists(path):  # saved before and removed from Stash: the file is still good
                fetch_media(media["url"], path, ctx.version, max_bytes=saving.MAX_BYTES[media["kind"]],
                            extra_host=_extra_host())
                written.append(path)
            fraction = (n + 1) / len(plan) * 0.8
            _save_update(ctx, post_id, progress=fraction)
            log.progress(fraction)
        paths = [p for _, p in plan]
        _, options = library.libraries(ctx.stash)
        library.scan(ctx.stash, paths, options)
        job = ctx.stash.gql(RUN_TASK, {"id": PLUGIN_ID, "description": "imaglr: crediting a saved post",
                                       "args": {"mode": "task_save_apply", "post_id": post_id}})["runPluginTask"]
        _save_update(ctx, post_id, status="scanning", progress=0.85, files=json.dumps(paths), stash_job_id=str(job))
    except (SaveFailed, MediaRefused) as e:
        _fail(ctx, post_id, str(e), written)
    except ImaglrError as e:
        _fail(ctx, post_id, _imaglr_message(e), written)
    except (OSError, StashError) as e:
        log.warning(f"saving post {post_id} failed: {e}")
        _fail(ctx, post_id, f"Couldn't save the files: {e}", written)
    return None


def _fail(ctx: Context, post_id: str, message: str, written: list[str]) -> None:
    for path in written:
        try:
            os.remove(path)
        except OSError:
            pass
    _save_update(ctx, post_id, status="failed", error=message)


def task_save_apply(ctx: Context) -> None:
    """After the scan: find what Stash made of each saved file and write the credit, the matched tags,
    performers and studio onto it; a post with several files also becomes a gallery."""
    post_id = ctx.arg("post_id")
    row = _save_row(ctx, post_id)
    if row is None or row["status"] != "scanning":
        return None
    try:
        post = json.loads(row["post"])
        files = json.loads(row["files"] or "[]")
        refs, missing = [], []
        for path in files:
            ref = library.find_by_path(ctx.stash, path)
            (refs if ref else missing).append(ref or path)
        if not refs:
            raise SaveFailed("Stash didn't add the saved files. Check the save folder is in a library that takes "
                             "pictures and videos, then save again.")
        config = _settings(ctx)
        names = library.match_names(ctx.stash, post["tags"], {config.queue_tag.casefold(), config.done_tag.casefold()})
        fields: dict[str, Any] = {"title": saving.title_text(post), "details": saving.details_text(post),
                                  "urls": saving.stash_urls(post), "tag_ids": names["tag_ids"],
                                  "performer_ids": names["performer_ids"]}
        if saving.stash_date(post):
            fields["date"] = saving.stash_date(post)
        if names["studio_id"]:
            fields["studio_id"] = names["studio_id"]
        custom = saving.custom_fields(post)
        for ref in refs:
            library.apply_credit(ctx.stash, ref, {**fields, "custom_fields": {"partial": custom}})
        if len(files) > 1:
            gallery = library.create_gallery(ctx.stash, {**fields, "custom_fields": custom},
                                             [r["id"] for r in refs if r["kind"] == "image"])
            for ref in refs:
                if ref["kind"] == "scene":
                    library.apply_credit(ctx.stash, ref, {"gallery_ids": [gallery]})
            refs.append({"kind": "gallery", "id": gallery})
        error = None
        if missing:
            error = (f"Stash didn't add {len(missing)} of the files. Check the save folder is in a library that "
                     "takes pictures and videos.")
        _save_update(ctx, post_id, status="failed" if missing else "done", progress=1, refs=json.dumps(refs), error=error)
    except SaveFailed as e:
        _save_update(ctx, post_id, status="failed", error=str(e))
    except StashError as e:
        log.warning(f"crediting saved post {post_id} failed: {e}")
        _save_update(ctx, post_id, status="failed", error=f"Stash refused the credit: {e}")
    return None


# ---- reblogging ----------------------------------------------------------------------------------------
def op_reblog(ctx: Context) -> dict[str, Any]:
    """Reblog a post to one of the user's blogs, straight away (the page asks first)."""
    blog = blogs.get_blog(ctx.db, ctx.arg("blog_id", int))
    if blog is None:
        raise UserError("That blog has been removed. Choose another.")
    post_id = str(ctx.arg("post_id"))
    if not post_id.isdigit():
        raise UserError("That isn't an imaglr post.")
    try:
        ctx.imaglr(blog).repost(post_id)
    except ImaglrError as e:
        raise UserError(_imaglr_message(e, blog, doing="reblog")) from None
    return {"ok": True, "blog": {"id": blog["id"], "name": blog["name"]}}


OPERATIONS = {
    "browse": op_browse,
    "post_find": op_post_find,
    "media_preview": op_media_preview,
    "save_setup": op_save_setup,
    "save_folder_set": op_save_folder_set,
    "save_post": op_save_post,
    "save_status": op_save_status,
    "reblog": op_reblog,
}

TASKS = {
    "task_save": task_save,
    "task_save_apply": task_save_apply,
}

# SPDX-License-Identifier: AGPL-3.0-only
"""Sync likes: save every post the user has liked on imaglr that isn't in their Stash library yet.

The one bulk save the plugin offers, by the owner's decision: every like is a post the user chose, unlike a whole
creator or tag, which imaglr asked tools not to download in bulk. It is started by hand, runs as a Stash task the
user can stop, and keeps within imaglr's rate limits (a page of 50 likes per request, waiting when imaglr asks).

New likes only (the default): imaglr lists likes newest first, so once SYNC_KNOWN_RUN posts in a row are already
saved, the rest were synced before and the sync stops. "All my likes" goes through every page.

Saving reuses the single-save steps (browse_ops): each post's files are downloaded, then one scan of all of them
is queued, then one task credits them all, with the user's import rules and exact name matches (no review).
Progress lives in the plugin's key-value store, for the Likes tab to show.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from . import browse_ops, log, saving
from .context import Context, UserError
from .db import now_iso
from .imaglr import ImaglrError
from .settings import PLUGIN_ID
from .stash import StashError, library

STATE_KEY = "likes_sync"
PAGE = 50  # likes per request (imaglr's largest page)
SYNC_KNOWN_RUN = 20  # new likes only: this many already-saved posts in a row means the rest were synced before
MAX_PAGES = 200  # 10,000 likes at most in one run
PAUSE = 0.5  # seconds between imaglr requests, well inside its 5,000 an hour
MAX_WAIT = 120  # longest wait imaglr may ask for before a sync gives up for now
STALE_SECONDS = 3600  # a save left half-done this long ago was interrupted


def state(ctx: Context) -> dict[str, Any]:
    return json.loads(ctx.db.kv_get(STATE_KEY) or "{}")


def _set(ctx: Context, **changes: Any) -> dict[str, Any]:
    current = {**state(ctx), **changes}
    ctx.db.kv_set(STATE_KEY, json.dumps(current))
    return current


def _stopped(ctx: Context) -> bool:
    return bool(state(ctx).get("stop"))


def _call(ctx: Context, fn, *args):
    """An imaglr request, paced, waiting (once or twice) when imaglr asks to slow down."""
    for attempt in range(3):
        time.sleep(PAUSE)
        try:
            return fn(*args)
        except ImaglrError as e:
            if e.code != "rate_limited" or attempt == 2 or (e.retry_after or 60) > MAX_WAIT:
                raise
            _set(ctx, note=f"imaglr asked to slow down: waiting {int(e.retry_after or 60)} s")
            time.sleep(e.retry_after or 60)
    return None


def _job_alive(ctx: Context, job_id: str | None) -> bool:
    if not job_id:
        return False
    try:
        jobs = ctx.stash.gql("{ jobQueue { id } }")["jobQueue"] or []
    except StashError:
        return True  # can't tell: assume it is
    return any(str(j["id"]) == str(job_id) for j in jobs)


# ---- operations ----------------------------------------------------------------------------------------
def op_sync_status(ctx: Context) -> dict[str, Any]:
    """Where the sync is. A sync whose Stash task has gone (stopped from Stash's Tasks page, or Stash restarted)
    is marked as stopped."""
    current = state(ctx)
    if current.get("running") and not _job_alive(ctx, current.get("job_id")):
        current = _set(ctx, running=False, finished_at=now_iso(), error=current.get("error") or "Stopped before it finished.")
    return {"sync": current}


def op_sync_likes(ctx: Context) -> dict[str, Any]:
    """Start a sync as a Stash task. `everything`: go through all likes, not just the new ones."""
    config = browse_ops._require_enabled(ctx)
    if not config.save_folder:
        raise UserError("Choose where saved posts go first.")
    libs, _ = library.libraries(ctx.stash)
    if saving.library_for(config.save_folder, libs) is None or not saving.writable(config.save_folder):
        raise UserError("Stash can't save into the save folder. Choose another in the plugin's Settings.")
    if op_sync_status(ctx)["sync"].get("running"):
        raise UserError("Your likes are already being synced.")
    blog = browse_ops._blog(ctx)
    _set(ctx, running=True, stop=False, everything=bool(ctx.args.get("everything")), blog_id=blog["id"],
         blog=blog["name"], started_at=now_iso(), finished_at=None, phase="reading", seen=0, new=0, known=0,
         skipped=0, failed=0, saved=0, error=None, note=None, job_id=None)
    job = ctx.stash.gql(browse_ops.RUN_TASK, {"id": PLUGIN_ID, "description": f"imaglr: syncing the likes of {blog['name'] or 'your blog'}",
                                             "args": {"mode": "task_sync_likes"}})["runPluginTask"]
    return {"sync": _set(ctx, job_id=str(job))}


def op_sync_stop(ctx: Context) -> dict[str, Any]:
    """Ask the sync to stop after the post it's on (what's downloaded by then is still saved and credited)."""
    return {"sync": _set(ctx, stop=True)}


# ---- tasks ---------------------------------------------------------------------------------------------
def _clear_stale(ctx: Context) -> None:
    """Saves left half-done by an earlier sync that was stopped hard."""
    cutoff = datetime.fromtimestamp(time.time() - STALE_SECONDS, timezone.utc).isoformat(timespec="seconds")
    ctx.db.execute("UPDATE saves SET status='failed', error='Interrupted.' WHERE status IN ('queued','downloading') "
                   "AND updated_at < ?", (cutoff,))


def task_sync_likes(ctx: Context) -> None:
    """Go through the likes newest first, downloading every post not yet in the library; then queue one scan of
    all the new files and one task to credit them."""
    current = state(ctx)
    if not current.get("running"):
        return None
    _clear_stale(ctx)
    config = browse_ops._settings(ctx)
    blog = browse_ops.blogs.get_blog(ctx.db, int(current["blog_id"]))
    if blog is None:
        _set(ctx, running=False, finished_at=now_iso(), error="That blog has been removed.")
        return None
    client = ctx.imaglr(blog)
    counts = {"seen": 0, "new": 0, "known": 0, "skipped": 0, "failed": 0}
    known_run, nxt = 0, None
    paths_all: list[str] = []
    synced: list[str] = []
    try:
        for _ in range(MAX_PAGES):
            if _stopped(ctx):
                break
            page = _call(ctx, client.likes, nxt, PAGE)
            posts = [saving.normalize_post(p) for p in page.posts]
            credited = [saving.credit(p)["id"] for p in posts]
            refs = library.saved_refs(ctx.stash, credited)
            for post, cid in zip(posts, credited):
                if _stopped(ctx):
                    break
                counts["seen"] += 1
                if not post["media"]:
                    counts["skipped"] += 1
                    continue
                row = browse_ops._save_row(ctx, cid)
                if refs.get(cid) or (row and row["status"] in browse_ops.IN_PROGRESS) or cid in synced:
                    counts["known"] += 1
                    known_run += 1
                    continue
                known_run = 0
                if post["original"]:  # saved as the original, with its own tags and caption, when still shown
                    try:
                        original = saving.normalize_post(_call(ctx, client.post, post["original"]["id"]))
                        if original["media"]:
                            post = original
                    except ImaglrError:
                        pass
                now = now_iso()
                ctx.db.execute("INSERT OR REPLACE INTO saves(post_id, status, progress, blog_id, post, files, refs, error, mapping, "
                               "created_at, updated_at) VALUES(?, 'downloading', 0, ?, ?, '[]', '[]', NULL, NULL, ?, ?)",
                               (cid, blog["id"], json.dumps(post), now, now))
                written: list[str] = []
                try:
                    paths = browse_ops.download_files(ctx, post, config.save_folder, written)
                    browse_ops._save_update(ctx, cid, status="scanning", progress=0.85, files=json.dumps(paths))
                    paths_all += paths
                    synced.append(cid)
                    counts["new"] += 1
                except Exception as e:  # noqa: BLE001 - one post failing never stops the sync
                    browse_ops._fail(ctx, cid, browse_ops.failure_message(cid, e), written)
                    counts["failed"] += 1
                _set(ctx, **counts)
            nxt = page.next
            if not nxt or (not current.get("everything") and known_run >= SYNC_KNOWN_RUN):
                break
            _set(ctx, **counts)
            log.info(f"likes sync: {counts['seen']} likes read, {counts['new']} new")
    except ImaglrError as e:
        _set(ctx, error=browse_ops._imaglr_message(e, blog))
    except StashError as e:
        _set(ctx, error=f"Stash refused: {e}")
    _set(ctx, **counts)
    if not synced:
        _set(ctx, running=False, phase="done", finished_at=now_iso())
        return None
    _, options = library.libraries(ctx.stash)
    library.scan(ctx.stash, paths_all, options)
    job = ctx.stash.gql(browse_ops.RUN_TASK, {"id": PLUGIN_ID, "description": f"imaglr: crediting {len(synced)} synced likes",
                                             "args": {"mode": "task_sync_apply", "post_ids": ",".join(synced)}})["runPluginTask"]
    _set(ctx, phase="crediting", job_id=str(job))
    return None


def task_sync_apply(ctx: Context) -> None:
    """After the scan: credit every post the sync downloaded."""
    ids = [i for i in str(ctx.arg("post_ids")).split(",") if i]
    saved = failed = 0
    for n, post_id in enumerate(ids, start=1):
        status = browse_ops.apply_one(ctx, post_id)
        saved += status == "done"
        failed += status == "failed"
        log.progress(n / len(ids))
    current = state(ctx)
    _set(ctx, running=False, phase="done", finished_at=now_iso(), saved=saved, failed=int(current.get("failed") or 0) + failed)
    return None


OPERATIONS = {
    "sync_likes": op_sync_likes,
    "sync_status": op_sync_status,
    "sync_stop": op_sync_stop,
}

TASKS = {
    "task_sync_likes": task_sync_likes,
    "task_sync_apply": task_sync_apply,
}

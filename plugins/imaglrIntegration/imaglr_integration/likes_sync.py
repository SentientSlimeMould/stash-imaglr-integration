# SPDX-License-Identifier: AGPL-3.0-only
"""Sync likes and import collections: save every post the user has liked, or bookmarked into one of their imaglr
collections, that isn't in their Stash library yet.

The bulk saves the plugin offers, by the owner's decision: every like and every bookmark is a post the user chose,
unlike a whole creator or tag, which imaglr asked tools not to download in bulk. A run is started by hand, runs as
a Stash task the user can stop, and keeps within imaglr's rate limits (a page of 50 per request, waiting when
imaglr asks). One run at a time, likes or a collection: they share this state.

Likes, new only (the default): imaglr lists likes newest first, so once SYNC_KNOWN_RUN posts in a row are already
saved, the rest were synced before and the sync stops. "All my likes" goes through every page.

A collection is always brought up to date: every page is read, only what's missing is downloaded, and every post
of the collection in the library, new or saved before, gets the collection's tag (library.collection_tag). "All
saved" (every bookmark) is imported the same way, without a tag.

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
TAG_REFS_KEY = "sync_tag_refs"  # a collection import: what was already in the library, to tag once it's done
PAGE = 50  # likes per request (imaglr's largest page)
SYNC_KNOWN_RUN = 20  # new likes only: this many already-saved posts in a row means the rest were synced before
MAX_PAGES = 200  # 10,000 likes at most in one run
PAUSE = 0.5  # seconds between imaglr requests, well inside its 5,000 an hour
MAX_WAIT = 120  # longest wait imaglr may ask for before a sync gives up for now
STATUS_PAGES = 10  # "x of y in your library" for collections of up to 500 posts
ALL_SAVED = "All saved"
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


def _start(ctx: Context, description: str, **fields: Any) -> dict[str, Any]:
    """Start a run as a Stash task, once the save folder can take saves and nothing else is running."""
    config = browse_ops._settings(ctx)
    if not config.save_folder:
        raise UserError("Choose where saved posts go first.")
    libs, _ = library.libraries(ctx.stash)
    if saving.library_for(config.save_folder, libs) is None or not saving.writable(config.save_folder):
        raise UserError("Stash can't save into the save folder. Choose another in the plugin's Settings.")
    running = op_sync_status(ctx)["sync"]
    if running.get("running"):
        what = f"“{running.get('collection_name')}” is" if running.get("source") == "collection" else "Your likes are"
        raise UserError(f"{what} already being saved to your library. Wait for it to finish, or stop it.")
    ctx.db.kv_set(TAG_REFS_KEY, "[]")
    fresh = {"running": True, "stop": False, "everything": False, "source": "likes", "collection_id": None,
             "collection_name": None, "started_at": now_iso(), "finished_at": None, "phase": "reading", "seen": 0,
             "new": 0, "known": 0, "skipped": 0, "gone": 0, "failed": 0, "saved": 0, "error": None, "note": None,
             "job_id": None}
    _set(ctx, **{**fresh, **fields})
    job = ctx.stash.gql(browse_ops.RUN_TASK, {"id": PLUGIN_ID, "description": description,
                                             "args": {"mode": "task_sync_likes"}})["runPluginTask"]
    return {"sync": _set(ctx, job_id=str(job))}


def op_sync_likes(ctx: Context) -> dict[str, Any]:
    """Start a sync of the likes. `everything`: go through all likes, not just the new ones."""
    blog = browse_ops._blog(ctx)
    return _start(ctx, f"imaglr: syncing the likes of {blog['name'] or 'your blog'}", blog_id=blog["id"],
                  blog=blog["name"], everything=bool(ctx.args.get("everything")))


def op_import_collection(ctx: Context) -> dict[str, Any]:
    """Start importing one of the browsing blog's imaglr collections (or "all": every bookmark) into the library."""
    blog = browse_ops._blog(ctx)
    collection = browse_ops._collection_id(ctx)
    name = ALL_SAVED
    if collection:
        try:
            found = next((c for c in ctx.imaglr(blog).collections() if str(c["id"]) == collection), None)
        except ImaglrError as e:
            raise UserError(browse_ops._imaglr_message(e, blog)) from None
        if found is None:
            raise UserError("That collection isn't on imaglr any more.")
        name = str(found.get("name") or "Untitled")
    return _start(ctx, f"imaglr: importing {name}", blog_id=blog["id"], blog=blog["name"], source="collection",
                  collection_id=collection or "all", collection_name=name)


def op_collection_status(ctx: Context) -> dict[str, Any]:
    """How much of a collection is in the library already: posts that can be saved (they have pictures or videos)
    and how many of them are. Reads at most STATUS_PAGES pages; for a bigger collection the counts are None."""
    blog = browse_ops._blog(ctx)
    client = ctx.imaglr(blog)
    collection = browse_ops._collection_id(ctx)
    credited: list[str] = []
    nxt = None
    try:
        for _ in range(STATUS_PAGES):
            entries, nxt = client.saved(collection, nxt, PAGE)
            credited += [saving.credit(p)["id"] for p in _posts(entries) if p["media"]]
            if not nxt:
                break
    except ImaglrError as e:
        raise UserError(browse_ops._imaglr_message(e, blog)) from None
    if nxt:
        return {"savable": None, "in_library": None}
    refs = library.saved_refs(ctx.stash, credited)
    return {"savable": len(credited), "in_library": sum(1 for c in credited if refs.get(c))}


def op_sync_stop(ctx: Context) -> dict[str, Any]:
    """Ask the sync to stop after the post it's on (what's downloaded by then is still saved and credited)."""
    return {"sync": _set(ctx, stop=True)}


# ---- tasks ---------------------------------------------------------------------------------------------
def _posts(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The posts of a page of bookmarks, leaving out those deleted or gone private since."""
    return [saving.normalize_post(e["post"]) for e in entries if isinstance(e.get("post"), dict)]


def _pages(ctx: Context, client: Any, current: dict[str, Any], counts: dict[str, int]):
    """The run's posts, a page at a time: the likes, or a collection's bookmarks (counting those that are gone)."""
    nxt = None
    for _ in range(MAX_PAGES):
        if _stopped(ctx):
            return  # Stop is honoured before asking imaglr for another page
        if current.get("source") == "collection":
            collection = None if current.get("collection_id") == "all" else current.get("collection_id")
            entries, nxt = _call(ctx, client.saved, collection, nxt, PAGE)
            posts = _posts(entries)
            counts["gone"] += len(entries) - len(posts)
        else:
            page = _call(ctx, client.likes, nxt, PAGE)
            posts, nxt = [saving.normalize_post(p) for p in page.posts], page.next
        yield posts
        if not nxt:
            return


def _collection_tag_id(ctx: Context, current: dict[str, Any]) -> str | None:
    """The tag a collection import files its posts under (none for "All saved")."""
    if current.get("source") != "collection" or current.get("collection_id") == "all":
        return None
    return library.collection_tag(ctx.stash, str(current["collection_name"]))


def _tag_collection(ctx: Context, current: dict[str, Any], more: list[dict[str, str]] = ()) -> None:
    """File what the run found already in the library, and anything it just saved, under the collection's tag."""
    refs = json.loads(ctx.db.kv_get(TAG_REFS_KEY) or "[]") + list(more)
    if not refs:
        return
    try:
        tag_id = _collection_tag_id(ctx, current)
        if tag_id:
            library.add_tag(ctx.stash, refs, tag_id)
    except StashError as e:
        _set(ctx, error=f"Stash didn't tag the collection: {e}")


def _clear_stale(ctx: Context) -> None:
    """Saves left half-done by an earlier sync that was stopped hard."""
    cutoff = datetime.fromtimestamp(time.time() - STALE_SECONDS, timezone.utc).isoformat(timespec="seconds")
    ctx.db.execute("UPDATE saves SET status='failed', error='Interrupted.' WHERE status IN ('queued','downloading') "
                   "AND updated_at < ?", (cutoff,))


def task_sync_likes(ctx: Context) -> None:
    """Go through the likes (or a collection) newest first, downloading every post not yet in the library; then
    queue one scan of all the new files and one task to credit them (and tag the collection)."""
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
    collection = current.get("source") == "collection"
    counts = {"seen": 0, "new": 0, "known": 0, "skipped": 0, "gone": 0, "failed": 0}
    known_run = 0
    paths_all: list[str] = []
    synced: list[str] = []
    already: list[dict[str, str]] = []  # a collection's posts saved before: tagged at the end
    try:
        for posts in _pages(ctx, client, current, counts):
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
                    already += refs.get(cid) or []
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
            _set(ctx, **counts)
            log.info(f"{'import' if collection else 'likes sync'}: {counts['seen']} posts read, {counts['new']} new")
            if not collection and not current.get("everything") and known_run >= SYNC_KNOWN_RUN:
                break
    except ImaglrError as e:
        _set(ctx, error=browse_ops._imaglr_message(e, blog))
    except StashError as e:
        _set(ctx, error=f"Stash refused: {e}")
    _set(ctx, **counts)
    ctx.db.kv_set(TAG_REFS_KEY, json.dumps(already))
    if not synced:
        _tag_collection(ctx, current)
        _set(ctx, running=False, phase="done", finished_at=now_iso())
        return None
    _, options = library.libraries(ctx.stash)
    library.scan(ctx.stash, paths_all, options)
    what = f"posts from {current['collection_name']}" if collection else "synced likes"
    job = ctx.stash.gql(browse_ops.RUN_TASK, {"id": PLUGIN_ID, "description": f"imaglr: crediting {len(synced)} {what}",
                                             "args": {"mode": "task_sync_apply", "post_ids": ",".join(synced)}})["runPluginTask"]
    _set(ctx, phase="crediting", job_id=str(job))
    return None


def task_sync_apply(ctx: Context) -> None:
    """After the scan: credit every post the run downloaded, then tag a collection's posts."""
    ids = [i for i in str(ctx.arg("post_ids")).split(",") if i]
    saved = failed = 0
    new_refs: list[dict[str, str]] = []
    for n, post_id in enumerate(ids, start=1):
        status = browse_ops.apply_one(ctx, post_id)
        saved += status == "done"
        failed += status == "failed"
        row = browse_ops._save_row(ctx, post_id)
        new_refs += json.loads(row["refs"] or "[]") if row else []
        log.progress(n / len(ids))
    current = state(ctx)
    _tag_collection(ctx, current, new_refs)
    _set(ctx, running=False, phase="done", finished_at=now_iso(), saved=saved, failed=int(current.get("failed") or 0) + failed)
    return None


OPERATIONS = {
    "sync_likes": op_sync_likes,
    "sync_status": op_sync_status,
    "sync_stop": op_sync_stop,
    "import_collection": op_import_collection,
    "collection_status": op_collection_status,
}

TASKS = {
    "task_sync_likes": task_sync_likes,
    "task_sync_apply": task_sync_apply,
}

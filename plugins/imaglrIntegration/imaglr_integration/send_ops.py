# SPDX-License-Identifier: AGPL-3.0-only
"""Operations around sending: edit an item, start the send task, cancel, recover, retry the follow-up.

The send itself runs as a Stash task (see jobs.py). `send` starts that task through Stash's own
runPluginTask so the job appears on Stash's Tasks page, and records the job id on the item.
"""

from __future__ import annotations

import json
import math
import os

from typing import Any

from . import blogs, jobs, services
from . import settings as plugin_settings
from . import items as repo
from .cleanup import cleanup_prepared
from .media import ffmpeg_cmd as fc
from .context import Context, UserError
from .db import now_iso
from .stash import api
from .settings import PLUGIN_ID
from .tags.pipeline import MAX_TAG_LEN, MAX_TAGS

IN_FLIGHT = ("exporting", "sending")
EDITABLE = {"tags", "caption", "blog_id", "action", "crop", "in_s", "out_s", "mute", "flip", "format", "codec", "max_edge", "loop",
            "gif_width"}
FORMATS = ("video", "gif", "webp")
CODECS = ("h264", "hevc")
LOOPS = ("forward", "boomerang")
MAX_EDGES = (None, 1280, 854)  # as the source, 720p, 480p
MAX_CLIP_SECONDS = services.MAX_CLIP_SECONDS
ASPECTS = ("original", "9:16", "4:5", "1:1")

RUN_TASK = """
mutation($id: ID!, $description: String, $args: Map) {
  runPluginTask(plugin_id: $id, description: $description, args_map: $args)
}
"""


def _item(ctx: Context) -> dict[str, Any]:
    item = repo.get_item(ctx.db, ctx.arg("item_id"))
    if item is None:
        raise UserError("That item no longer exists. Refresh the page.")
    return item


def _clean_tags(tags: Any, lowercase: bool) -> list[str]:
    if not isinstance(tags, list):
        raise UserError("Tags must be a list.")
    out: list[str] = []
    for tag in tags:
        tag = " ".join(str(tag).split())
        tag = tag.lower() if lowercase else tag
        if not tag or tag.lower() in (t.lower() for t in out):
            continue
        if len(tag) > MAX_TAG_LEN:
            raise UserError(f"Tags can be at most {MAX_TAG_LEN} characters: {tag[:20]}…")
        out.append(tag)
    if len(out) > MAX_TAGS:
        raise UserError(f"imaglr allows up to {MAX_TAGS} tags per post.")
    return out


def op_item_update(ctx: Context) -> dict[str, Any]:
    item = _item(ctx)
    if item["status"] in IN_FLIGHT + ("sent",):
        raise UserError("This item is being sent or has been sent, so it can't be changed.")
    owner = repo.set_of(ctx.db, item["id"])
    if owner and (repo.get_item(ctx.db, owner) or {}).get("status") in IN_FLIGHT + ("sent",):
        raise UserError("This file's post is being sent or has been sent, so it can't be changed.")
    if not isinstance(ctx.args.get("changes"), dict):
        raise UserError("Nothing to change.")
    changes = {k: v for k, v in ctx.args["changes"].items() if k in EDITABLE}
    if "tags" in changes:
        changes["tags"] = _clean_tags(changes["tags"], not plugin_settings.load(ctx.stash).keep_tag_case)
        if changes["tags"] != item["tags"]:
            changes["tags_auto"] = False  # the user has taken over; rules and Stash tags no longer flow through
    if (ctx.args.get("changes") or {}).get("tags_auto") is True:
        # Back to automatic: the current suggestions replace the edited list.
        config = plugin_settings.load(ctx.stash)
        fresh = services.refresh_item_tags(ctx.stash, ctx.db, config, repo.update_item(ctx.db, item["id"], tags_auto=True) or item)
        changes.pop("tags", None)
        changes.pop("tags_auto", None)
        item = fresh
    if "caption" in changes:
        changes["caption"] = str(changes["caption"] or "")[:10000]
    if "blog_id" in changes and changes["blog_id"] is not None:
        if blogs.get_blog(ctx.db, int(changes["blog_id"])) is None:
            raise UserError("That blog is no longer set up.")
        changes["blog_id"] = int(changes["blog_id"])
    if "action" in changes and changes["action"] not in (None,) + blogs.ACTIONS:
        raise UserError("Unknown send action.")
    if "crop" in changes:
        crop = changes["crop"] if isinstance(changes["crop"], dict) else {}
        if crop.get("aspect") not in ASPECTS:
            raise UserError("Unknown crop.")
        changes["crop"] = {"aspect": crop["aspect"], "position": min(max(float(crop.get("position", 0.5)), 0.0), 1.0)}
        edges = fc.clean_edges(crop.get("edges"))
        if fc.has_edges(edges):
            changes["crop"]["edges"] = edges
        if changes["crop"] != item["crop"]:
            changes.update(output_path=None, output_bytes=None, output_mime=None, output_note=None)  # prepare again
    if "format" in changes and changes["format"] not in FORMATS:
        raise UserError("Unknown format.")
    if "codec" in changes and changes["codec"] not in CODECS:
        raise UserError("Unknown codec.")
    if "max_edge" in changes:
        changes["max_edge"] = int(changes["max_edge"]) if changes["max_edge"] else None
        if changes["max_edge"] not in MAX_EDGES:
            raise UserError("Unknown picture size.")
    if "loop" in changes and changes["loop"] not in LOOPS:
        raise UserError("Unknown loop.")
    if "gif_width" in changes:
        changes["gif_width"] = int(changes["gif_width"]) if changes["gif_width"] else None
        if changes["gif_width"] is not None and changes["gif_width"] not in {r[0] for r in fc.GIF_LADDER[1:]}:
            raise UserError("Unknown GIF size.")
    if {"in_s", "out_s", "mute", "flip", "format", "codec", "max_edge", "loop", "gif_width"} & set(changes):
        if item["kind"] != "clip":
            raise UserError("Only clips can be trimmed, muted, flipped or made into GIFs.")
        in_s = round(float(changes["in_s"]), 3) if "in_s" in changes else float(item["in_s"] or 0)
        out_s = round(float(changes["out_s"]), 3) if "out_s" in changes else float(item["out_s"] or 0)
        if not (math.isfinite(in_s) and math.isfinite(out_s)):
            raise UserError("The clip times must be numbers.")
        if in_s < 0 or out_s - in_s < 0.1:
            raise UserError("The clip must end after it starts.")
        if out_s - in_s > MAX_CLIP_SECONDS:
            raise UserError(f"Clips can be at most {MAX_CLIP_SECONDS // 60} minutes long.")
        changes.update(in_s=in_s, out_s=out_s, mute=bool(changes.get("mute", item["mute"])),
                       flip=bool(changes.get("flip", item["flip"])), format=changes.get("format", item["format"]),
                       codec=changes.get("codec", item["codec"]), max_edge=changes.get("max_edge", item["max_edge"]),
                       loop=changes.get("loop", item["loop"]), gif_width=changes.get("gif_width", item["gif_width"]))
        keys = ("in_s", "out_s", "mute", "flip", "format", "codec", "max_edge", "loop", "gif_width")
        if tuple(changes[k] for k in keys) != tuple(item[k] for k in keys):
            changes.update(output_path=None, output_bytes=None, output_mime=None, output_note=None,
                           size_guard_retried=False)  # export again
        if item["stash_marker_id"] and (changes["in_s"], changes["out_s"]) != (item["in_s"], item["out_s"]):
            marker = api.find_marker(ctx.stash, item["stash_marker_id"])
            if marker:  # keep Stash's marker in step with the trimmed clip
                api.marker_update(ctx.stash, marker, seconds=changes["in_s"], end_seconds=changes["out_s"])
                if marker.scene and changes["in_s"] != marker.seconds:
                    api.generate_marker_previews(ctx.stash, marker.scene.id)  # Stash names them by start time
    if item["status"] == "failed" or (item["status"] == "ready" and changes.get("output_path", True) is None):
        changes.update(status="pending", error_code=None, error_detail=None)
    return {"item": repo.update_item(ctx.db, item["id"], **changes)}


def op_send(ctx: Context) -> dict[str, Any]:
    item = _item(ctx)
    if item["status"] in IN_FLIGHT:
        raise UserError("This is already being sent.")
    if item["status"] == "sent":
        raise UserError("This has already been sent.")
    if repo.set_of(ctx.db, item["id"]):
        raise UserError("This file is part of a post. Send the post instead.")
    changes: dict[str, Any] = {}
    if ctx.args.get("blog_id") is not None:
        changes["blog_id"] = ctx.arg("blog_id", int)
    if ctx.args.get("action") is not None:
        if ctx.args["action"] not in blogs.ACTIONS:
            raise UserError("Unknown send action.")
        changes["action"] = ctx.args["action"]
    if changes:
        item = repo.update_item(ctx.db, item["id"], **changes)  # type: ignore[assignment]
    try:
        blog = jobs.choose_blog(ctx, item)
    except jobs.JobFailed as e:
        raise UserError(e.detail) from None
    return _start(ctx, item, blog, blogs.resolve_action(blog, item["action"]), bool(ctx.args.get("gif_fallback")))


def _start(ctx: Context, item: dict[str, Any], blog: dict[str, Any], action: str, gif_fallback: bool = False,
           format_override: str | None = None) -> dict[str, Any]:
    """Queue the send task in Stash (it appears on Stash's Tasks page) and record its job id."""
    title = item["source_title"] or "post"
    # Marked busy first: the task only runs items in this state, so a second Send can't queue it twice, and
    # the item's own action setting is left alone (Send all may run it as a draft).
    repo.update_item(ctx.db, item["id"], status="exporting", progress=0, stash_job_id=None,
                     cancel_requested=False, error_code=None, error_detail=None)
    try:
        job_id = ctx.stash.gql(RUN_TASK, {
            "id": PLUGIN_ID,
            "description": f"imaglr: sending {title[:60]} to {blog['name'] or 'imaglr'} ({action})",
            "args": {"mode": "task_send", "item_id": item["id"], "action": action,
                     "gif_fallback": gif_fallback, "format_override": format_override},
        })["runPluginTask"]
    except Exception:
        repo.update_item(ctx.db, item["id"], status="pending", error_code="stash_error",
                         error_detail="Stash couldn't start the send task.")
        raise
    item = repo.update_item(ctx.db, item["id"], stash_job_id=str(job_id))  # type: ignore[assignment]
    return {"item": item, "job_id": job_id}


LONG_GIF_SECONDS = 15  # beyond this a GIF gets heavy; Send all offers to send such clips as videos

SKIP_REASONS = {
    "no_blog": "no blog chosen",
    "paused": "blog needs attention",
    "busy": "already sending",
    "sent": "already sent",
    "gone": "no longer on the page",
    "in_post": "part of a post (send the post)",
}


def plan_send_all(ctx: Context, item_ids: list[str]) -> list[dict[str, Any]]:
    """What Send all would do with each item: its blog and action, or why it's skipped.
    Never publishes straight away: an item that would be published is saved as a draft."""
    all_blogs = blogs.list_blogs(ctx.db)
    plan = []
    for item_id in dict.fromkeys(str(i) for i in item_ids):
        item = repo.get_item(ctx.db, item_id)
        entry: dict[str, Any] = {"id": item_id}
        if item is None:
            entry["skip"] = "gone"
        elif item["status"] in IN_FLIGHT:
            entry["skip"] = "busy"
        elif item["status"] == "sent":
            entry["skip"] = "sent"
        elif repo.set_of(ctx.db, item_id):
            entry["skip"] = "in_post"
        else:
            blog = blogs.get_blog(ctx.db, item["blog_id"]) if item["blog_id"] else (all_blogs[0] if len(all_blogs) == 1 else None)
            if blog is None:
                entry["skip"] = "no_blog"
            elif blog["paused_reason"]:
                entry["skip"] = "paused"
            else:
                action = blogs.resolve_action(blog, item["action"])
                entry.update(blog_id=blog["id"], blog=blog["name"] or f"Blog {blog['id']}",
                             action="draft" if action == "publish" else action, downgraded=action == "publish")
                members = repo.set_members(ctx.db, item_id) if item["kind"] == "set" else [item]
                gifs = [m for m in members if m["kind"] == "clip" and m["format"] in ("gif", "webp")]  # animated: no sound, image limit
                if gifs:
                    entry["gif"] = True
                    entry["long_gif"] = any(((m["out_s"] or 0) - (m["in_s"] or 0)) > LONG_GIF_SECONDS for m in gifs)
        if "skip" in entry:
            entry["reason"] = SKIP_REASONS[entry["skip"]]
        plan.append(entry)
    return plan


def op_send_all(ctx: Context) -> dict[str, Any]:
    """Send several items, each as its own post (dry_run: just say what would happen)."""
    ids = ctx.args.get("item_ids")
    if not isinstance(ids, list) or not ids:
        raise UserError("Nothing to send.")
    plan = plan_send_all(ctx, ids)
    if not ctx.args.get("dry_run"):
        long_as_video = ctx.args.get("long_gifs_as_video", True)
        gif_fallback = ctx.args.get("gif_fallback", True)
        for entry in plan:
            if "skip" not in entry:
                item = repo.get_item(ctx.db, entry["id"])
                override = "video" if (long_as_video and entry.get("long_gif")) else None
                _start(ctx, item, blogs.get_blog(ctx.db, entry["blog_id"]), entry["action"],  # type: ignore[arg-type]
                       bool(gif_fallback), override)
    return {"plan": plan}


def op_cancel(ctx: Context) -> dict[str, Any]:
    item = _item(ctx)
    if item["status"] not in IN_FLIGHT:
        return {"item": item}
    queue = {j["id"]: j["status"] for j in ctx.stash.gql("{ jobQueue { id status } }")["jobQueue"] or []}
    if queue.get(item["stash_job_id"]) == "READY":  # not started yet: just remove it from Stash's queue
        ctx.stash.gql("mutation($id: ID!) { stopJob(job_id: $id) }", {"id": item["stash_job_id"]})
        return {"item": repo.update_item(ctx.db, item["id"], status="ready" if item["output_path"] else "pending",
                                         progress=0, error_code="cancelled", error_detail="Stopped.")}
    return {"item": repo.update_item(ctx.db, item["id"], cancel_requested=True)}  # the task stops itself


def op_send_status(ctx: Context) -> dict[str, Any]:
    """Progress of everything not yet settled, from the database only: what the page polls every couple of
    seconds while a send runs, instead of re-discovering the whole queue."""
    rows = repo.list_items(ctx.db, statuses=repo.ACTIVE_STATUSES)
    return {"items": [{k: r[k] for k in ("id", "status", "progress", "error_code", "error_detail")} for r in rows]}


def op_recover(ctx: Context) -> dict[str, Any]:
    """Runs when the page loads: items left mid-send by a Stash restart or a killed job are marked failed
    (so they can be retried), and old prepared files are cleaned up."""
    config = plugin_settings.load(ctx.stash)
    cleanup_prepared(ctx.db, os.path.join(ctx.data_dir, "prepared"), config.prepared_retention_days)
    stuck = repo.list_items(ctx.db, statuses=IN_FLIGHT)
    if not stuck:
        return {"recovered": 0}
    running = {j["id"] for j in ctx.stash.gql("{ jobQueue { id } }")["jobQueue"] or []}
    recovered = 0
    for item in stuck:
        if item["stash_job_id"] not in running:
            repo.update_item(ctx.db, item["id"], status="failed", progress=0, cancel_requested=False,
                             error_code="interrupted",
                             error_detail="This send didn't finish (Stash restarted, or the task was stopped). Send it again.")
            recovered += 1
    return {"recovered": recovered}


def op_retry_follow_up(ctx: Context) -> dict[str, Any]:
    item = _item(ctx)
    if not item["followup_failed"]:
        return {"item": item}
    try:
        return {"item": jobs.retry_follow_up(ctx, item)}
    except jobs.JobFailed as e:
        raise UserError(e.detail) from None


def _thumb(member: dict[str, Any]) -> str | None:
    """A thumbnail URL (relative to Stash's base) that needs no lookup: Stash's URLs for images and
    marker screenshots are predictable, and a still's grabbed frame is served by the plugin."""
    if member["stash_image_id"]:
        return f"image/{member['stash_image_id']}/thumbnail"
    if member["stash_marker_id"] and member["stash_scene_id"]:
        return f"scene/{member['stash_scene_id']}/scene_marker/{member['stash_marker_id']}/screenshot"
    if member["kind"] == "still" and member["source_path"] and os.path.isfile(member["source_path"]):
        return services.prepared_url(member["id"], member["source_path"])
    return None


def _thumb_fallback(member: dict[str, Any]) -> str | None:
    """What to show if the thumbnail can't be loaded: a clip's marker may have been deleted since it was
    sent, but its scene's screenshot is still there. Images have nothing to fall back to."""
    if member["stash_marker_id"] and member["stash_scene_id"] and not member["stash_image_id"]:
        return f"scene/{member['stash_scene_id']}/screenshot"
    return None


def _sent_view(ctx: Context, item: dict[str, Any], blog_names: dict[int, str]) -> dict[str, Any]:
    """A sent post as the Sent tab's card and detail dialog need it."""
    members = repo.set_members(ctx.db, item["id"]) if item["kind"] == "set" else [item]
    files = [{
        "id": m["id"], "kind": m["kind"], "title": m["source_title"], "thumb": _thumb(m),
        "thumb_fallback": _thumb_fallback(m),
        "stash_image_id": m["stash_image_id"], "stash_scene_id": m["stash_scene_id"],
        "stash_marker_id": m["stash_marker_id"], "in_s": m["in_s"],
        "send_format": m["format"], "output_note": m["output_note"],
    } for m in members]
    first = next((f for f in files if f["thumb"]), None)
    return {
        "id": item["id"],
        "kind": item["kind"],
        "title": files[0]["title"] if files else item["source_title"],
        "files": files,
        "thumb": first["thumb"] if first else None,
        "thumb_fallback": first["thumb_fallback"] if first else None,
        "blog_id": item["blog_id"],
        "blog": blog_names.get(item["blog_id"]) if item["blog_id"] else None,
        "sent_as": item["sent_as"],
        "sent_at": item["sent_at"],
        "draft_id": item["draft_id"],
        "post_url": item["post_url"],
        "tags": item["tags"],
        "caption": item["caption"],
        "dropped_tags": item["dropped_tags"],
        "followup_failed": item["followup_failed"],
        "action": item["action"],
        "error_code": item["error_code"],
        "error_detail": item["error_detail"],
        "output_note": item["output_note"],
    }


SENT_SORTS = {"sent": "sent_at", "name": "source_title COLLATE NOCASE", "blog": "blog_id"}


def op_sent_list(ctx: Context) -> dict[str, Any]:
    """One page of sent posts, searched, filtered and sorted on the backend (history grows without limit)."""
    a = ctx.args
    per_page = min(max(int(a.get("per_page") or 40), 1), 1000)
    page = max(int(a.get("page") or 1), 1)
    where, params = ["status='sent'", "id NOT IN (SELECT item_id FROM set_members)"], []  # type: ignore[var-annotated]
    q = " ".join(str(a.get("q") or "").split())
    if q:
        where.append("source_title LIKE ? ESCAPE '\\'")
        params.append("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if a.get("blog_id"):
        where.append("blog_id=?")
        params.append(int(a["blog_id"]))
    if a.get("sent_as") in blogs.ACTIONS:
        where.append("sent_as=?")
        params.append(a["sent_as"])
    order = SENT_SORTS.get(str(a.get("sort") or "sent"), "sent_at")
    direction = "ASC" if a.get("dir") == "asc" else "DESC"
    names = {b["id"]: b["name"] or f"Blog {b['id']}" for b in blogs.list_blogs(ctx.db)}
    clause = " AND ".join(where)
    total = ctx.db.fetchone(f"SELECT COUNT(*) AS n FROM items WHERE {clause}", tuple(params))["n"]
    rows = ctx.db.fetchall(
        f"SELECT * FROM items WHERE {clause} ORDER BY {order} {direction}, sent_at DESC LIMIT ? OFFSET ?",
        tuple(params + [per_page, (page - 1) * per_page]),
    )
    return {"items": [_sent_view(ctx, repo.decode(r), names) for r in rows], "total": total,
            "page": page, "per_page": per_page,
            "blogs": [{"id": i, "name": n} for i, n in names.items()]}


def op_sent_detail(ctx: Context) -> dict[str, Any]:
    item = _item(ctx)
    if item["status"] != "sent":
        raise UserError("That post hasn't been sent.")
    names = {b["id"]: b["name"] or f"Blog {b['id']}" for b in blogs.list_blogs(ctx.db)}
    view = _sent_view(ctx, item, names)
    # Which Stash tag (or performer/studio name) each dropped imaglr tag came from, so "Always drop" can
    # write a rule for it. Unknown when the tag was typed by hand or the source has changed since.
    origins: dict[str, str] = {}
    if view["dropped_tags"]:
        config = plugin_settings.load(ctx.stash)
        members = repo.set_members(ctx.db, item["id"]) if item["kind"] == "set" else [item]
        for m in members:
            _, sugg = services.source_suggestions(ctx.stash, ctx.db, config, m)
            for t in (sugg.active + sugg.greyed) if sugg else []:
                origins.setdefault(t.tag.lower(), t.original)
    view["dropped"] = [{"tag": t, "from": origins.get(t.lower())} for t in view["dropped_tags"]]
    return {"item": view}


def _rules(ctx: Context) -> dict[str, Any]:
    rows = ctx.db.fetchall("SELECT stash_tag, imaglr_tags FROM tag_rules ORDER BY stash_tag COLLATE NOCASE")
    return {"rules": [{"stash_tag": r["stash_tag"], "imaglr_tags": json.loads(r["imaglr_tags"])} for r in rows]}


def op_tag_rule_set(ctx: Context) -> dict[str, Any]:
    """Whenever this Stash tag is suggested, send these imaglr tags instead ([] = never suggest it)."""
    stash_tag = " ".join(str(ctx.arg("stash_tag")).split())
    targets = ctx.args.get("imaglr_tags")
    if not stash_tag or not isinstance(targets, list):
        raise UserError("Choose a Stash tag and the imaglr tags to send for it.")
    cleaned = _clean_tags(targets, not plugin_settings.load(ctx.stash).keep_tag_case)
    ts = now_iso()
    ctx.db.execute(
        "INSERT INTO tag_rules(stash_tag, imaglr_tags, created_at, updated_at) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(stash_tag) DO UPDATE SET imaglr_tags=excluded.imaglr_tags, updated_at=excluded.updated_at",
        (stash_tag, json.dumps(cleaned), ts, ts),
    )
    return _rules(ctx)


def op_tag_rule_list(ctx: Context) -> dict[str, Any]:
    return {**_rules(ctx), "lowercase_tags": not plugin_settings.load(ctx.stash).keep_tag_case}


def op_tag_rule_delete(ctx: Context) -> dict[str, Any]:
    ctx.db.execute("DELETE FROM tag_rules WHERE stash_tag=?", (str(ctx.arg("stash_tag")),))
    return _rules(ctx)


def op_stash_tags_find(ctx: Context) -> dict[str, Any]:
    """Existing Stash tags by name, for choosing the Stash side of a tag rule."""
    text = str(ctx.args.get("q") or "").strip()
    return {"tags": [t.name for t in api.find_tags(ctx.stash, text)] if text else []}


def op_tags_suggest(ctx: Context) -> dict[str, Any]:
    """Autocomplete for the tag editor: tags sent before (most used first), then Stash tag names."""
    text = " ".join(str(ctx.args.get("q") or "").split())
    if not text:
        return {"tags": []}
    lowercase = not plugin_settings.load(ctx.stash).keep_tag_case
    used = [r["tag"] for r in ctx.db.fetchall(
        "SELECT tag FROM used_tags WHERE tag LIKE ? ESCAPE '\\' ORDER BY use_count DESC, last_used DESC LIMIT 10",
        ("%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",),
    )]
    stash = [t.name.lower() if lowercase else t.name for t in api.find_tags(ctx.stash, text)]
    out: list[str] = []
    for tag in used + stash:
        if tag.lower() not in (t.lower() for t in out) and len(tag) <= MAX_TAG_LEN:
            out.append(tag)
    return {"tags": out[:10]}


def task_send(ctx: Context) -> None:
    jobs.run_send(ctx, ctx.arg("item_id"), ctx.args.get("action"), bool(ctx.args.get("gif_fallback")),
                  ctx.args.get("format_override"))


OPERATIONS = {
    "item_update": op_item_update,
    "send": op_send,
    "send_all": op_send_all,
    "cancel": op_cancel,
    "recover": op_recover,
    "retry_follow_up": op_retry_follow_up,
    "sent_list": op_sent_list,
    "sent_detail": op_sent_detail,
    "tag_rule_set": op_tag_rule_set,
    "tag_rule_list": op_tag_rule_list,
    "tag_rule_delete": op_tag_rule_delete,
    "stash_tags_find": op_stash_tags_find,
    "tags_suggest": op_tags_suggest,
}

TASKS = {
    "task_send": task_send,
    "send_status": op_send_status,
}

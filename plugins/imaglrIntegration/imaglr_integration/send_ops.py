# SPDX-License-Identifier: AGPL-3.0-only
"""Operations around sending: edit an item, start the send task, cancel, recover, retry the follow-up.

The send itself runs as a Stash task (see jobs.py). `send` starts that task through Stash's own
runPluginTask so the job appears on Stash's Tasks page, and records the job id on the item.
"""

from __future__ import annotations

from typing import Any

from . import blogs, jobs
from . import settings as plugin_settings
from . import items as repo
from .context import Context, UserError
from .stash import api
from .settings import PLUGIN_ID
from .tags.pipeline import MAX_TAG_LEN, MAX_TAGS

IN_FLIGHT = ("exporting", "sending")
EDITABLE = {"tags", "caption", "blog_id", "action", "crop", "in_s", "out_s", "mute"}
MAX_CLIP_SECONDS = 600
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
    changes = {k: v for k, v in (ctx.args.get("changes") or {}).items() if k in EDITABLE}
    if "tags" in changes:
        changes["tags"] = _clean_tags(changes["tags"], not plugin_settings.load(ctx.stash).keep_tag_case)
    if "caption" in changes:
        changes["caption"] = str(changes["caption"] or "")[:10000]
    if "blog_id" in changes and changes["blog_id"] is not None:
        if blogs.get_blog(ctx.db, int(changes["blog_id"])) is None:
            raise UserError("That blog is no longer set up.")
        changes["blog_id"] = int(changes["blog_id"])
    if "action" in changes and changes["action"] not in (None,) + blogs.ACTIONS:
        raise UserError("Unknown send action.")
    if "crop" in changes:
        crop = changes["crop"] or {}
        if crop.get("aspect") not in ASPECTS:
            raise UserError("Unknown crop.")
        changes["crop"] = {"aspect": crop["aspect"], "position": min(max(float(crop.get("position", 0.5)), 0.0), 1.0)}
        if changes["crop"] != item["crop"]:
            changes.update(output_path=None, output_bytes=None, output_mime=None)  # prepare again
    if {"in_s", "out_s", "mute"} & set(changes):
        if item["kind"] != "clip":
            raise UserError("Only clips can be trimmed or muted.")
        in_s = float(changes.get("in_s", item["in_s"]) or 0)
        out_s = float(changes.get("out_s", item["out_s"]) or 0)
        if in_s < 0 or out_s - in_s < 0.1:
            raise UserError("The clip must end after it starts.")
        if out_s - in_s > MAX_CLIP_SECONDS:
            raise UserError(f"Clips can be at most {MAX_CLIP_SECONDS // 60} minutes long.")
        changes.update(in_s=round(in_s, 3), out_s=round(out_s, 3), mute=bool(changes.get("mute", item["mute"])))
        if (changes["in_s"], changes["out_s"], changes["mute"]) != (item["in_s"], item["out_s"], item["mute"]):
            changes.update(output_path=None, output_bytes=None, output_mime=None)  # export again
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
    action = blogs.resolve_action(blog, item["action"])
    title = item["source_title"] or "post"
    job_id = ctx.stash.gql(RUN_TASK, {
        "id": PLUGIN_ID,
        "description": f"imaglr: sending {title[:60]} to {blog['name'] or 'imaglr'} ({action})",
        "args": {"mode": "task_send", "item_id": item["id"]},
    })["runPluginTask"]
    item = repo.update_item(ctx.db, item["id"], status="exporting", progress=0, stash_job_id=str(job_id),
                            cancel_requested=False, error_code=None, error_detail=None)  # type: ignore[assignment]
    return {"item": item, "job_id": job_id}


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


def op_recover(ctx: Context) -> dict[str, Any]:
    """Items left mid-send by a Stash restart or a killed job are marked failed, so they can be retried."""
    stuck = repo.list_items(ctx.db, statuses=IN_FLIGHT)
    if not stuck:
        return {"recovered": 0}
    running = {j["id"] for j in ctx.stash.gql("{ jobQueue { id } }")["jobQueue"] or []}
    recovered = 0
    for item in stuck:
        if item["stash_job_id"] not in running:
            repo.update_item(ctx.db, item["id"], status="failed", progress=0, cancel_requested=False,
                             error_code="interrupted", error_detail="Stash stopped before this finished. Send it again.")
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


def _sent_view(ctx: Context, item: dict[str, Any], blog_names: dict[int, str]) -> dict[str, Any]:
    members = repo.set_members(ctx.db, item["id"]) if item["kind"] == "set" else [item]
    thumbs = [f"image/{m['stash_image_id']}/thumbnail" for m in members if m["stash_image_id"]]
    return {
        "id": item["id"],
        "kind": item["kind"],
        "title": members[0]["source_title"] if members else item["source_title"],
        "files": len(members),
        "thumb": thumbs[0] if thumbs else None,
        "blog": blog_names.get(item["blog_id"]) if item["blog_id"] else None,
        "sent_as": item["sent_as"],
        "sent_at": item["sent_at"],
        "draft_id": item["draft_id"],
        "post_url": item["post_url"],
        "tags": item["tags"],
        "dropped_tags": item["dropped_tags"],
        "followup_failed": item["followup_failed"],
        "action": item["action"],
        "error_code": item["error_code"],
        "error_detail": item["error_detail"],
        "stash_image_ids": [m["stash_image_id"] for m in members if m["stash_image_id"]],
    }


def op_sent_list(ctx: Context) -> dict[str, Any]:
    members = repo.members_index(ctx.db)
    names = {b["id"]: b["name"] or f"Blog {b['id']}" for b in blogs.list_blogs(ctx.db)}
    rows = ctx.db.fetchall("SELECT * FROM items WHERE status='sent' ORDER BY sent_at DESC LIMIT ?",
                           (int(ctx.args.get("limit") or 200),))
    return {"items": [_sent_view(ctx, repo.decode(r), names) for r in rows if r["id"] not in members]}


def op_tag_map_set(ctx: Context) -> dict[str, Any]:
    """Always map a Stash tag to another imaglr tag, or (imaglr_tag null) never suggest it."""
    from .db import now_iso

    stash_tag = " ".join(str(ctx.arg("stash_tag")).split())
    target = ctx.args.get("imaglr_tag")
    target = " ".join(str(target).split()) or None if target is not None else None
    if not stash_tag or (target and len(target) > MAX_TAG_LEN):
        raise UserError("That tag can't be mapped.")
    ts = now_iso()
    ctx.db.execute(
        "INSERT INTO tag_map(stash_tag, imaglr_tag, created_at, updated_at) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(stash_tag) DO UPDATE SET imaglr_tag=excluded.imaglr_tag, updated_at=excluded.updated_at",
        (stash_tag, target, ts, ts),
    )
    return {"ok": True}


def op_tag_map_list(ctx: Context) -> dict[str, Any]:
    rows = ctx.db.fetchall("SELECT stash_tag, imaglr_tag FROM tag_map ORDER BY stash_tag COLLATE NOCASE")
    return {"rules": rows}


def op_tag_map_delete(ctx: Context) -> dict[str, Any]:
    ctx.db.execute("DELETE FROM tag_map WHERE stash_tag=?", (str(ctx.arg("stash_tag")),))
    return op_tag_map_list(ctx)


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
    jobs.run_send(ctx, ctx.arg("item_id"))


OPERATIONS = {
    "item_update": op_item_update,
    "send": op_send,
    "cancel": op_cancel,
    "recover": op_recover,
    "retry_follow_up": op_retry_follow_up,
    "sent_list": op_sent_list,
    "tag_map_set": op_tag_map_set,
    "tag_map_list": op_tag_map_list,
    "tag_map_delete": op_tag_map_delete,
    "tags_suggest": op_tags_suggest,
}

TASKS = {
    "task_send": task_send,
}

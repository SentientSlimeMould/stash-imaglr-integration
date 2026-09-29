# SPDX-License-Identifier: AGPL-3.0-only
"""Operations for clips: stills from a clip, and the imaglr tab on Stash's scene page
(this scene's markers, queueing them, creating a new marker)."""

from __future__ import annotations

from typing import Any

from . import items as repo
from . import jobs, services, settings
from .context import Context, UserError
from .stash import Marker, api
from .stash.queries import MARKER_FIELDS

SCENE_MARKERS = (
    """
query SceneMarkers($id: ID!) {
  findSceneMarkers(scene_marker_filter: { scenes: { value: [$id], modifier: INCLUDES } },
                   filter: { per_page: -1, sort: "seconds", direction: ASC }) {
    scene_markers { """
    + MARKER_FIELDS
    + """ }
  }
}
"""
)


def _workflow(ctx: Context):
    config = settings.load(ctx.stash)
    return config, api.workflow_tags(ctx.stash, config.queue_tag, config.done_tag)


def op_still_create(ctx: Context) -> dict[str, Any]:
    """Grab the frame at `t` from a clip as a new picture item, with the clip's tags."""
    clip = repo.get_item(ctx.db, ctx.arg("item_id"))
    if clip is None or clip["kind"] != "clip":
        raise UserError("That clip no longer exists. Refresh the page.")
    t = ctx.arg("t", float)
    still = repo.create_item(ctx.db, kind="still", source_item_id=clip["id"], still_t=t, tags=clip["tags"],
                             source_title=f"{clip['source_title']} · still at {t:.1f}s", blog_id=clip["blog_id"])
    try:
        frame = jobs.grab_still(ctx, clip, t, still["id"])
    except jobs.JobFailed as e:
        repo.delete_item(ctx.db, still["id"])
        raise UserError(e.detail) from None
    still = repo.update_item(ctx.db, still["id"], source_path=frame)
    return {"item_id": still["id"], "thumb": services.prepared_url(still["id"], frame)}  # type: ignore[index]


def _marker_view(ctx: Context, marker: Marker, queue_id: str, done_id: str) -> dict[str, Any]:
    ids = marker.all_tag_ids
    item = repo.active_for_marker(ctx.db, marker.id)
    return {
        "id": marker.id,
        "title": marker.display_title,
        "seconds": marker.seconds,
        "end_seconds": marker.end_seconds,
        "primary_tag": marker.primary_tag.name if marker.primary_tag else None,
        "queued": queue_id in ids,
        "sent": done_id in ids,
        "queue_is_primary": bool(marker.primary_tag and marker.primary_tag.id == queue_id),
        "item_id": item["id"] if item else None,
        "status": item["status"] if item else None,
        "thumb": services.relative_url(marker.screenshot_url),
    }


def op_scene_markers(ctx: Context) -> dict[str, Any]:
    _, (queue_tag, done_tag) = _workflow(ctx)
    data = ctx.stash.gql(SCENE_MARKERS, {"id": ctx.arg("scene_id")})
    markers = [Marker.parse(m) for m in data["findSceneMarkers"]["scene_markers"]]
    return {
        "markers": [_marker_view(ctx, m, queue_tag.id, done_tag.id) for m in markers],
        "tags": services.queue_tags((queue_tag, done_tag)),
    }


def op_marker_set_queued(ctx: Context) -> dict[str, Any]:
    """Add or remove the queue tag on a marker (as a secondary tag)."""
    _, (queue_tag, done_tag) = _workflow(ctx)
    marker = api.find_marker(ctx.stash, ctx.arg("marker_id"))
    if marker is None:
        raise UserError("That marker no longer exists.")
    queued = bool(ctx.args.get("queued"))
    secondary = [t.id for t in marker.tags if t.id != queue_tag.id]
    if not queued and marker.primary_tag and marker.primary_tag.id == queue_tag.id:
        raise UserError(f"'{queue_tag.name}' is this marker's primary tag. Change the primary tag in Stash first.")
    if queued:
        secondary.append(queue_tag.id)
    else:
        item = repo.active_for_marker(ctx.db, marker.id)
        if item and item["status"] in ("exporting", "sending"):
            raise UserError("This clip is being sent right now.")
    api.marker_update(ctx.stash, marker, tag_ids=secondary)
    marker = api.find_marker(ctx.stash, marker.id)
    return {"marker": _marker_view(ctx, marker, queue_tag.id, done_tag.id)}  # type: ignore[arg-type]


def op_marker_create(ctx: Context) -> dict[str, Any]:
    """Create a marker on a scene, already queued for imaglr, and return its clip item."""
    config, (queue_tag, done_tag) = _workflow(ctx)
    seconds = ctx.arg("seconds", float)
    end_seconds = ctx.arg("end_seconds", float)
    if seconds < 0 or end_seconds - seconds < 0.1:
        raise UserError("Set the end after the start.")
    primary = str(ctx.args.get("primary_tag_id") or queue_tag.id)
    tag_ids = [] if primary == queue_tag.id else [queue_tag.id]
    title = str(ctx.args.get("title") or "").strip()
    marker_id = api.marker_create(ctx.stash, ctx.arg("scene_id"), seconds, end_seconds, primary, tag_ids, title)
    api.generate_marker_previews(ctx.stash, ctx.arg("scene_id"))
    marker = api.find_marker(ctx.stash, marker_id)
    item = services.item_from_marker(ctx.db, config, marker)  # type: ignore[arg-type]
    return {"marker": _marker_view(ctx, marker, queue_tag.id, done_tag.id), "item_id": item["id"]}  # type: ignore[arg-type]


def op_tags_find(ctx: Context) -> dict[str, Any]:
    text = str(ctx.args.get("q") or "").strip()
    return {"tags": [{"id": t.id, "name": t.name} for t in api.find_tags(ctx.stash, text)] if text else []}


OPERATIONS = {
    "still_create": op_still_create,
    "scene_markers": op_scene_markers,
    "marker_set_queued": op_marker_set_queued,
    "marker_create": op_marker_create,
    "tags_find": op_tags_find,
}

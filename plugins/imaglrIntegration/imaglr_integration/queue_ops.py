# SPDX-License-Identifier: AGPL-3.0-only
"""Operations behind the Post to imaglr page's queue and Stash's "Add to imaglr" menu entries."""

from __future__ import annotations

from typing import Any

from . import items as repo
from . import blogs, services, settings
from .context import Context, UserError
from .stash import api
from .tags.pipeline import merge_suggestions

GALLERY_IMAGE_IDS = """
query GalleryImageIds($id: ID!) {
  findImages(image_filter: { galleries: { value: [$id], modifier: INCLUDES } },
             filter: { per_page: -1, sort: "path", direction: ASC }) { images { id } }
}
"""


def _workflow(ctx: Context):
    config = settings.load(ctx.stash)
    return config, api.workflow_tags(ctx.stash, config.queue_tag, config.done_tag)


def _retry_pending_swap(ctx: Context, tags, **source) -> bool:
    """A source still carrying the queue tag because its send's tag swap failed: swap now (or leave it for
    next time) rather than queueing it again, which would send a duplicate. True = not a queue candidate."""
    sent = repo.sent_with_pending_swap(ctx.db, **source)
    if sent is None:
        return False
    from . import jobs  # local: jobs imports services, not the other way round

    if not jobs.swap_source_tags(ctx, [sent], tags[0], tags[1]):
        owner = repo.set_of(ctx.db, sent["id"]) or sent["id"]
        post = repo.get_item(ctx.db, owner)
        if post and post["error_code"] == "tag_swap_failed":
            repo.update_item(ctx.db, owner, error_code=None, error_detail=None)
    return True


def op_queue(ctx: Context) -> dict[str, Any]:
    """Everything waiting to be sent: queued markers and images (as items), stills, and posts grouping them.
    Each card says which tab it belongs on."""
    config, tags = _workflow(ctx)
    db = ctx.db
    markers = api.queued_markers(ctx.stash, tags[0].id)
    scenes = api.queued_scenes(ctx.stash, tags[0].id)
    images = api.queued_images(ctx.stash, tags[0].id)
    seen = services.mark_seen(db, [f"marker:{m.id}" for m in markers] + [f"scene:{s.id}" for s in scenes]
                              + [f"image:{i.id}" for i in images])

    cards: dict[str, dict[str, Any]] = {}
    for marker in markers:
        if _retry_pending_swap(ctx, tags, marker_id=marker.id):
            continue
        item = services.item_from_marker(db, config, marker)
        cards[item["id"]] = services.clip_card(item, marker, seen.get(f"marker:{marker.id}"))
    for scene in scenes:  # a scene with the queue tag is shared whole, without a marker
        if _retry_pending_swap(ctx, tags, scene_id=scene.id):
            continue
        item = services.item_from_scene(db, config, scene)
        cards[item["id"]] = services.clip_card(item, None, seen.get(f"scene:{scene.id}"), scene=scene)
    for image in images:
        if _retry_pending_swap(ctx, tags, image_id=image.id):
            continue
        item = services.item_from_image(db, config, image)
        cards[item["id"]] = services.image_card(item, image, seen.get(f"image:{image.id}"))
    for item in repo.list_items(db, kinds=("still",), statuses=repo.ACTIVE_STATUSES):
        cards[item["id"]] = services.still_card(item)

    member_of = repo.members_index(db)
    out, posts = [], {}  # type: ignore[var-annotated]
    for item_id, card in cards.items():
        set_id = member_of.get(item_id)
        if set_id:
            posts.setdefault(set_id, []).append(card)
        else:
            out.append(card)
    for set_id, members in posts.items():
        post = repo.get_item(db, set_id)
        order = [m["id"] for m in repo.set_members(db, set_id)]
        members.sort(key=lambda c: order.index(c["id"]))
        out.append(services.post_card(post, members))  # type: ignore[arg-type]
    sent = db.fetchone("SELECT COUNT(*) AS n FROM items WHERE status='sent' "
                       "AND id NOT IN (SELECT item_id FROM set_members)")["n"]
    return {"items": out, "tags": services.queue_tags(tags), "sent_count": sent}


def _add_images(ctx: Context, image_ids: list[str], as_one_post: bool) -> dict[str, Any]:
    image_ids = [str(i) for i in dict.fromkeys(image_ids)]
    if not image_ids:
        raise UserError("No images selected.")
    if as_one_post and len(image_ids) > repo.MAX_SET_MEMBERS:
        raise UserError(f"An imaglr post holds up to {repo.MAX_SET_MEMBERS} images.")
    config, (queue_tag, _) = _workflow(ctx)
    already = {i.id for i in api.queued_images(ctx.stash, queue_tag.id)} & set(image_ids)
    api.images_add_tags(ctx.stash, image_ids, [queue_tag.id])
    services.mark_seen(ctx.db, [f"image:{i}" for i in image_ids])

    post_id = None
    if as_one_post:
        members = []
        for image_id in image_ids:
            image = api.find_image(ctx.stash, image_id)
            if image is None:
                raise UserError(f"Image {image_id} no longer exists in Stash.")
            members.append(services.item_from_image(ctx.db, config, image))
        try:
            post_id = services.create_post(ctx.db, [m["id"] for m in members])["id"]
        except services.PostError as e:
            raise UserError(str(e)) from None
    return {"added": len(image_ids) - len(already), "already": len(already), "post_id": post_id}


def op_add_scenes(ctx: Context) -> dict[str, Any]:
    """Queue whole scenes (from the ⋯ menu of Stash's scene list): tag them, as tagging by hand would."""
    ids = [str(i) for i in (ctx.args.get("scene_ids") or []) if str(i).strip()][:500]
    if not ids:
        raise UserError("No scenes selected.")
    config, (queue_tag, _) = _workflow(ctx)
    api.scenes_add_tags(ctx.stash, ids, [queue_tag.id])
    return {"added": len(ids), "tag": queue_tag.name}


def op_add_images(ctx: Context) -> dict[str, Any]:
    ids = ctx.args.get("image_ids")
    if not isinstance(ids, list):
        raise UserError("Missing argument: image_ids")
    return _add_images(ctx, ids, bool(ctx.args.get("as_one_post")))


def op_add_gallery(ctx: Context) -> dict[str, Any]:
    data = ctx.stash.gql(GALLERY_IMAGE_IDS, {"id": ctx.arg("gallery_id")})
    ids = [i["id"] for i in data["findImages"]["images"]]
    if not ids:
        raise UserError("This gallery has no images.")
    if len(ids) > repo.MAX_SET_MEMBERS:
        return {"added": 0, "already": 0, "post_id": None, "too_many": len(ids)}
    return _add_images(ctx, ids, True)


def op_post_create(ctx: Context) -> dict[str, Any]:
    ids = ctx.args.get("item_ids")
    if not isinstance(ids, list):
        raise UserError("Missing argument: item_ids")
    try:
        return {"post_id": services.create_post(ctx.db, [str(i) for i in ids])["id"]}
    except services.PostError as e:
        raise UserError(str(e)) from None


def op_post_split(ctx: Context) -> dict[str, Any]:
    """Split one post (post_id) or several (post_ids) into separate items."""
    ids = ctx.args.get("post_ids") if isinstance(ctx.args.get("post_ids"), list) else [ctx.arg("post_id")]
    try:
        for post_id in [str(i) for i in ids][:500]:
            services.dissolve_post(ctx.db, post_id)
    except services.PostError as e:
        raise UserError(str(e)) from None
    return {"ok": True}


def _item(ctx: Context) -> dict[str, Any]:
    item = repo.get_item(ctx.db, ctx.arg("item_id"))
    if item is None:
        raise UserError("That item no longer exists. Refresh the page.")
    return item


def _file_view(ctx: Context, config, member: dict[str, Any]):
    """One file of an item for the editor, plus the tag suggestions its Stash source gives."""
    source, sugg = services.source_suggestions(ctx.stash, ctx.db, config, member)
    if member["kind"] == "clip" and member["stash_marker_id"]:
        card = services.clip_card(member, source, None)
    elif services.is_whole_scene(member):
        card = services.clip_card(member, None, None, scene=source)
    elif member["kind"] == "still":
        card = services.still_card(member)
        card["image"] = card["thumb"]
    else:
        card = services.image_card(member, source, None)
        card["image"] = services.relative_url(source.image_url) if source else None
    card.update({k: member[k] for k in ("crop", "in_s", "out_s", "mute", "flip", "format", "codec", "max_edge", "loop", "gif_width", "gif_fps", "output_note",
                                        "output_mime",
                                        "stash_marker_id", "stash_scene_id", "stash_image_id")})
    card["prepared"] = services.prepared_url(member["id"], member["output_path"]) if member["output_path"] else None
    return card, sugg


def op_item_detail(ctx: Context) -> dict[str, Any]:
    """Everything the editor needs: the item, its files, tag suggestions and the blogs to choose from."""
    item = _item(ctx)
    config = settings.load(ctx.stash)
    members = repo.set_members(ctx.db, item["id"]) if item["kind"] == "set" else [item]
    views = [_file_view(ctx, config, m) for m in members]
    suggestions = merge_suggestions([s for _, s in views if s is not None])
    # Automatic tags follow Stash and the rules: bring them up to date now that the sources are in hand.
    if item["kind"] == "set":
        fresh = [services.refresh_tags(ctx.db, m, s.active_names() if s else None) for m, (_, s) in zip(members, views)]
        item = services.refresh_tags(ctx.db, item, services.merged_tags(fresh))
    else:
        item = services.refresh_tags(ctx.db, item, suggestions.active_names() if views[0][1] else None)
    return {
        "item": {k: item[k] for k in ("id", "kind", "status", "tags", "caption", "blog_id", "action", "crop",
                                      "error_code", "error_detail", "progress", "source_title", "in_s", "out_s",
                                      "mute", "flip", "format", "codec", "max_edge", "loop", "gif_width", "gif_fps", "output_note", "hdr_warning", "tags_auto",
                                      "updated_at")},
        "files": [card for card, _ in views],
        "suggestions": suggestions.to_dict(),
        "blogs": [blogs.public(b) for b in blogs.list_blogs(ctx.db)],
        "lowercase_tags": not config.keep_tag_case,
        "queue_tag": config.queue_tag,
        "gif_target_mb": config.gif_target_mb,
    }


def op_post_arrange(ctx: Context) -> dict[str, Any]:
    """Reorder a post's files or drop some (dropped files stay queued as separate items)."""
    post = _item(ctx)
    if post["kind"] != "set" or post["status"] in services.BUSY_STATUSES:
        raise UserError("This post can't be changed now.")
    current = [m["id"] for m in repo.set_members(ctx.db, post["id"])]
    wanted = [str(i) for i in ctx.args.get("item_ids") or []]
    if not set(wanted) <= set(current) or len(set(wanted)) != len(wanted):
        raise UserError("Those files aren't all in this post. Refresh and try again.")
    if not wanted:
        services.dissolve_post(ctx.db, post["id"])
        return {"post_id": None}
    repo.set_member_ids(ctx.db, post["id"], wanted)
    return {"post_id": post["id"]}


def op_remove_from_queue(ctx: Context) -> dict[str, Any]:
    """Take items (item_id, or item_ids for several; a post means every file in it) off the imaglr page:
    removes the queue tag in Stash. Stills, which only exist here, are deleted."""
    ids = ctx.args.get("item_ids") if isinstance(ctx.args.get("item_ids"), list) else [ctx.arg("item_id")]
    removed = 0
    for item_id in [str(i) for i in ids][:500]:
        removed += _remove_one(ctx, item_id)
    return {"removed": removed}


def _remove_one(ctx: Context, item_id: str) -> int:
    item = repo.get_item(ctx.db, item_id)
    if item is None:
        return 0
    if item["status"] == "sent":
        raise UserError("This has been sent; it's on the Sent tab.")
    if item["status"] in services.BUSY_STATUSES:
        raise UserError("This can't be removed while it's being sent.")
    config, (queue_tag, _) = _workflow(ctx)
    members = repo.set_members(ctx.db, item["id"]) if item["kind"] == "set" else [item]
    if item["kind"] == "set" and any(m["status"] in services.BUSY_STATUSES for m in members):
        raise UserError("This can't be removed while it's being sent.")
    # Check every marker before changing anything in Stash, so a refusal leaves the post whole.
    markers = []
    for m in members:
        if not m["stash_marker_id"]:
            continue
        marker = api.find_marker(ctx.stash, m["stash_marker_id"])
        if marker is None:
            continue
        if marker.primary_tag and marker.primary_tag.id == queue_tag.id and not [t for t in marker.tags if t.id != queue_tag.id]:
            raise UserError(
                f'"{queue_tag.name}" is the only tag on the marker for {m["source_title"]}, and Stash markers must '
                "keep one tag. Give the marker another primary tag on the scene's Markers tab (or delete the marker there)."
            )
        markers.append(marker)
    image_ids = [m["stash_image_id"] for m in members if m["stash_image_id"]]
    if image_ids:
        api.images_remove_tags(ctx.stash, image_ids, [queue_tag.id])
    scene_ids = [m["stash_scene_id"] for m in members if services.is_whole_scene(m)]
    if scene_ids:
        api.scenes_remove_tags(ctx.stash, scene_ids, [queue_tag.id])
    for marker in markers:
        api.marker_remove_tag(ctx.stash, marker, queue_tag)
    for m in members:
        repo.delete_item(ctx.db, m["id"])
    if item["kind"] == "set":
        repo.delete_item(ctx.db, item["id"])
    return len(members)


OPERATIONS = {
    "item_detail": op_item_detail,
    "post_arrange": op_post_arrange,
    "remove_from_queue": op_remove_from_queue,
    "queue": op_queue,
    "add_images": op_add_images,
    "add_scenes": op_add_scenes,
    "add_gallery": op_add_gallery,
    "post_create": op_post_create,
    "post_split": op_post_split,
}

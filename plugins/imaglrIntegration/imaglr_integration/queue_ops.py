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


def op_queue(ctx: Context) -> dict[str, Any]:
    """Everything waiting to be sent: queued markers and images (as items), stills, and posts grouping them.
    Each card says which tab it belongs on."""
    config, tags = _workflow(ctx)
    db = ctx.db
    markers = api.queued_markers(ctx.stash, tags[0].id)
    images = api.queued_images(ctx.stash, tags[0].id)
    seen = services.mark_seen(db, [f"marker:{m.id}" for m in markers] + [f"image:{i.id}" for i in images])

    cards: dict[str, dict[str, Any]] = {}
    for marker in markers:
        item = services.item_from_marker(db, config, marker)
        cards[item["id"]] = services.clip_card(item, marker, seen.get(f"marker:{marker.id}"))
    for image in images:
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
    try:
        services.dissolve_post(ctx.db, ctx.arg("post_id"))
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
    if member["kind"] == "clip" and member["stash_marker_id"]:
        marker = api.find_marker(ctx.stash, member["stash_marker_id"])
        card = services.clip_card(member, marker, None)
        sugg = services.marker_suggestions(ctx.db, config, marker) if marker else None
    elif member["kind"] == "still":
        card = services.still_card(member)
        card["image"] = card["thumb"]
        source = repo.get_item(ctx.db, member["source_item_id"]) if member["source_item_id"] else None
        sugg = None
        if source and source["stash_marker_id"]:
            marker = api.find_marker(ctx.stash, source["stash_marker_id"])
            sugg = services.marker_suggestions(ctx.db, config, marker) if marker else None
    else:
        image = api.find_image(ctx.stash, member["stash_image_id"]) if member["stash_image_id"] else None
        card = services.image_card(member, image, None)
        card["image"] = services.relative_url(image.image_url) if image else None
        sugg = services.image_suggestions(ctx.db, config, image) if image else None
    card.update({k: member[k] for k in ("crop", "in_s", "out_s", "mute", "stash_marker_id", "stash_scene_id",
                                        "stash_image_id")})
    card["prepared"] = services.prepared_url(member["id"], member["output_path"]) if member["output_path"] else None
    return card, sugg


def op_item_detail(ctx: Context) -> dict[str, Any]:
    """Everything the editor needs: the item, its files, tag suggestions and the blogs to choose from."""
    item = _item(ctx)
    config = settings.load(ctx.stash)
    members = repo.set_members(ctx.db, item["id"]) if item["kind"] == "set" else [item]
    views = [_file_view(ctx, config, m) for m in members]
    suggestions = merge_suggestions([s for _, s in views if s is not None])
    return {
        "item": {k: item[k] for k in ("id", "kind", "status", "tags", "caption", "blog_id", "action", "crop",
                                      "error_code", "error_detail", "progress", "source_title", "in_s", "out_s",
                                      "mute", "hdr_warning")},
        "files": [card for card, _ in views],
        "suggestions": suggestions.to_dict(),
        "blogs": [blogs.public(b) for b in blogs.list_blogs(ctx.db)],
        "lowercase_tags": not config.keep_tag_case,
        "queue_tag": config.queue_tag,
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
    """Take an item (or every file in a post) off the imaglr page: removes the queue tag in Stash."""
    item = _item(ctx)
    if item["status"] in services.BUSY_STATUSES:
        raise UserError("This can't be removed while it's being sent.")
    config, (queue_tag, _) = _workflow(ctx)
    members = repo.set_members(ctx.db, item["id"]) if item["kind"] == "set" else [item]
    image_ids = [m["stash_image_id"] for m in members if m["stash_image_id"]]
    if image_ids:
        api.images_remove_tags(ctx.stash, image_ids, [queue_tag.id])
    for m in members:
        repo.delete_item(ctx.db, m["id"])
    if item["kind"] == "set":
        repo.delete_item(ctx.db, item["id"])
    return {"removed": len(members)}


OPERATIONS = {
    "item_detail": op_item_detail,
    "post_arrange": op_post_arrange,
    "remove_from_queue": op_remove_from_queue,
    "queue": op_queue,
    "add_images": op_add_images,
    "add_gallery": op_add_gallery,
    "post_create": op_post_create,
    "post_split": op_post_split,
}

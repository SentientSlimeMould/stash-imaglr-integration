# SPDX-License-Identifier: AGPL-3.0-only
"""Operations behind the Post to imaglr page's queue and Stash's "Add to imaglr" menu entries."""

from __future__ import annotations

from typing import Any

from . import items as repo
from . import blogs, services, settings
from .context import Context, UserError
from .stash import Image, api

GALLERY_IMAGE_IDS = """
query GalleryImageIds($id: ID!) {
  findImages(image_filter: { galleries: { value: [$id], modifier: INCLUDES } },
             filter: { per_page: -1, sort: "path", direction: ASC }) { images { id } }
}
"""


def _workflow(ctx: Context):
    config = settings.load(ctx.stash)
    return config, api.workflow_tags(ctx.stash, config.queue_tag, config.done_tag)


def op_images_queue(ctx: Context) -> dict[str, Any]:
    """Everything on the Images tab: queued Stash images as items, grouped into posts where grouped."""
    config, tags = _workflow(ctx)
    db = ctx.db
    queued = api.queued_images(ctx.stash, tags[0].id)
    seen = services.mark_seen(db, [f"image:{i.id}" for i in queued])
    by_item: dict[str, tuple[dict[str, Any], Image]] = {}
    for image in queued:
        item = services.item_from_image(db, config, image)
        by_item[item["id"]] = (item, image)

    member_of = repo.members_index(db)
    cards, posts = [], {}
    for item_id, (item, image) in by_item.items():
        card = services.image_card(item, image, seen.get(f"image:{image.id}"))
        set_id = member_of.get(item_id)
        if set_id:
            posts.setdefault(set_id, []).append(card)
        else:
            cards.append(card)
    for set_id in posts:
        post = repo.get_item(db, set_id)
        order = [m["id"] for m in repo.set_members(db, set_id)]
        members = sorted(posts[set_id], key=lambda c: order.index(c["id"]))
        cards.append(services.post_card(post, members))  # type: ignore[arg-type]
    return {"items": cards, "tags": services.queue_tags(tags)}


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


def op_item_detail(ctx: Context) -> dict[str, Any]:
    """Everything the editor needs: the item, its files, tag suggestions and the blogs to choose from."""
    item = _item(ctx)
    config = settings.load(ctx.stash)
    members = repo.set_members(ctx.db, item["id"]) if item["kind"] == "set" else [item]
    images = [api.find_image(ctx.stash, m["stash_image_id"]) if m["stash_image_id"] else None for m in members]
    files = []
    for member, image in zip(members, images):
        card = services.image_card(member, image, None)
        card["image"] = services.relative_url(image.image_url) if image else None
        card["crop"] = member["crop"]
        files.append(card)
    found = [i for i in images if i is not None]
    suggestions = services.post_suggestions(ctx.db, config, found) if found else None
    return {
        "item": {k: item[k] for k in ("id", "kind", "status", "tags", "caption", "blog_id", "action", "crop",
                                      "error_code", "error_detail", "progress", "source_title")},
        "files": files,
        "suggestions": suggestions.to_dict() if suggestions else {"active": [], "greyed": []},
        "blogs": [blogs.public(b) for b in blogs.list_blogs(ctx.db)],
        "lowercase_tags": not config.keep_tag_case,
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
    "images_queue": op_images_queue,
    "add_images": op_add_images,
    "add_gallery": op_add_gallery,
    "post_create": op_post_create,
    "post_split": op_post_split,
}

# SPDX-License-Identifier: AGPL-3.0-only
"""Turning Stash's queued markers and images into plugin items, grouping them into posts, and describing
them for the UI. Stash decides what is queued (the queue tag); the database holds edits and state."""

from __future__ import annotations

import urllib.parse
from typing import Any

from . import items as repo
from .db import Database, now_iso
from .settings import Settings
from .stash import Image, Tag
from .tags.pipeline import TagConfig, collect_image_sources, merge_suggestions, parse_patterns, suggest

SET_KINDS = ("image", "still", "clip")
BUSY_STATUSES = ("exporting", "sending", "sent")


class PostError(ValueError):
    pass


def tag_config(settings: Settings) -> TagConfig:
    return TagConfig(
        queue_tag=settings.queue_tag,
        done_tag=settings.done_tag,
        exclude_patterns=parse_patterns(settings.exclude_patterns),
        lowercase=not settings.keep_tag_case,
    )


def relative_url(url: str | None) -> str | None:
    """Stash builds media URLs from the plugin's own (server-side) request, so their host and any
    reverse-proxy prefix are wrong for the browser. Keep path and query; the UI prefixes its base URL."""
    if not url:
        return None
    parts = urllib.parse.urlsplit(url)
    return parts.path.lstrip("/") + (f"?{parts.query}" if parts.query else "")


def image_suggestions(db: Database, settings: Settings, image: Image):
    return suggest(collect_image_sources(image), tag_config(settings), repo.tag_mapping(db))


def item_from_image(db: Database, settings: Settings, image: Image) -> dict[str, Any]:
    """The image's current (unsent) item, creating it with suggested tags if needed."""
    existing = repo.active_for_image(db, image.id)
    kind = "clip" if image.is_video else "image"
    if existing and existing["kind"] != kind and existing["status"] not in BUSY_STATUSES:
        repo.delete_item(db, existing["id"])  # the file changed type in Stash since it was queued
        existing = None
    if existing:
        return existing
    tags = image_suggestions(db, settings, image).active_names()
    if kind == "clip":
        f = image.primary_file
        duration = f.duration if f and f.duration else None
        out_s = min(duration, settings.default_clip_seconds) if duration else settings.default_clip_seconds
        return repo.create_item(db, kind="clip", stash_image_id=image.id, source_title=image.display_title,
                                in_s=0.0, out_s=out_s, tags=tags)
    return repo.create_item(db, kind="image", stash_image_id=image.id, source_title=image.display_title, tags=tags)


def mark_seen(db: Database, keys: list[str]) -> dict[str, str]:
    """First time each queued Stash object was seen: the "Added" sort order."""
    ts = now_iso()
    for key in keys:
        db.execute("INSERT OR IGNORE INTO queue_seen(key, first_seen) VALUES(?, ?)", (key, ts))
    return {r["key"]: r["first_seen"] for r in db.fetchall("SELECT key, first_seen FROM queue_seen")}


def create_post(db: Database, item_ids: list[str]) -> dict[str, Any]:
    """Group items into one post (a set). Items already grouped elsewhere move here; a group left
    empty is removed. Members keep their own crop and processing; the post owns tags and caption."""
    ids = list(dict.fromkeys(item_ids))
    if not 1 <= len(ids) <= repo.MAX_SET_MEMBERS:
        raise PostError(f"A post holds 1 to {repo.MAX_SET_MEMBERS} files.")
    members = []
    for item_id in ids:
        item = repo.get_item(db, item_id)
        if item is None:
            raise PostError("One of those items no longer exists. Refresh and try again.")
        if item["kind"] not in SET_KINDS:
            raise PostError(f"{item['source_title']} can't be part of a post.")
        if item["status"] in BUSY_STATUSES:
            raise PostError(f"{item['source_title']} is {item['status']} and can't be regrouped.")
        members.append(item)
    old_sets = {repo.set_of(db, m["id"]) for m in members} - {None}
    for old in old_sets:
        if repo.get_item(db, old)["status"] in BUSY_STATUSES:  # type: ignore[index]
            raise PostError("Some of those items belong to a post that is being sent.")
    tags: list[str] = []
    for m in members:
        tags += [t for t in m["tags"] if t.lower() not in {x.lower() for x in tags}]
    blogs = {m["blog_id"] for m in members if m["blog_id"]}
    post = repo.create_item(
        db, kind="set", source_title=members[0]["source_title"], tags=tags[:30],
        blog_id=blogs.pop() if len(blogs) == 1 else None,
    )
    with db.transaction() as conn:
        conn.executemany("DELETE FROM set_members WHERE item_id=?", [(m["id"],) for m in members])
        conn.executemany(
            "INSERT INTO set_members(set_id, item_id, position) VALUES(?, ?, ?)",
            [(post["id"], m["id"], n) for n, m in enumerate(members)],
        )
    for old in old_sets:
        if not repo.set_members(db, old):
            repo.delete_item(db, old)
    return repo.get_item(db, post["id"])  # type: ignore[return-value]


def dissolve_post(db: Database, set_id: str) -> None:
    post = repo.get_item(db, set_id)
    if post is None or post["kind"] != "set":
        raise PostError("That post no longer exists.")
    if post["status"] in BUSY_STATUSES:
        raise PostError(f"This post is {post['status']} and can't be split.")
    repo.delete_item(db, set_id)  # members stay, as separate items


def post_suggestions(db: Database, settings: Settings, members: list[Image]):
    return merge_suggestions([image_suggestions(db, settings, image) for image in members])


def image_card(item: dict[str, Any], image: Image | None, first_seen: str | None) -> dict[str, Any]:
    f = image.primary_file if image else None
    return {
        "id": item["id"],
        "kind": item["kind"],
        "title": item["source_title"],
        "status": item["status"],
        "progress": item["progress"],
        "error_code": item["error_code"],
        "error_detail": item["error_detail"],
        "blog_id": item["blog_id"],
        "action": item["action"],
        "tag_count": len(item["tags"]),
        "stash_image_id": item["stash_image_id"],
        "thumb": relative_url(image.thumbnail_url) if image else None,
        "width": f.width if f else None,
        "height": f.height if f else None,
        "bytes": f.size if f else None,
        "format": f.image_format if f else None,
        "animated": bool(f and f.is_animated),
        "duration": f.duration if f and f.is_video else None,
        "created_at": image.created_at if image else item["created_at"],
        "date": image.date if image else None,
        "first_seen": first_seen,
        "in_stash_queue": image is not None,
    }


def post_card(post: dict[str, Any], member_cards: list[dict[str, Any]]) -> dict[str, Any]:
    card = {k: post[k] for k in ("id", "kind", "status", "progress", "error_code", "error_detail", "blog_id",
                                 "action")}
    card.update(
        title=member_cards[0]["title"] if member_cards else post["source_title"],
        tag_count=len(post["tags"]),
        members=member_cards,
        thumb=member_cards[0]["thumb"] if member_cards else None,
        bytes=sum(m["bytes"] or 0 for m in member_cards) or None,
        first_seen=min((m["first_seen"] or "" for m in member_cards), default=None) or None,
        created_at=post["created_at"],
    )
    return card


def queue_tags(tags: tuple[Tag, Tag]) -> dict[str, Any]:
    queue, done = tags
    return {"queue": {"id": queue.id, "name": queue.name}, "done": {"id": done.id, "name": done.name}}

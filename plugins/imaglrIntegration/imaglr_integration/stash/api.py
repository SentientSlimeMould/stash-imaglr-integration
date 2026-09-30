# SPDX-License-Identifier: AGPL-3.0-only
"""High-level Stash reads and the few writes reference spec §5 allows, on top of StashClient.gql.

Writes: sceneMarkerCreate / sceneMarkerUpdate (in/out write-back, queue -> done tag swap), bulkImageUpdate
tag ADD/REMOVE, and tagCreate for the two workflow tags only.
"""

from __future__ import annotations

from typing import Any

from .. import log
from . import paths
from . import queries as q
from .client import StashClient, StashError
from .models import Image, Marker, Scene, Tag

PAGE_SIZE = 100


# ---- status ------------------------------------------------------------------------------
def version(client: StashClient) -> str:
    data = client.gql(q.VERSION)
    return str((data.get("version") or {}).get("version") or "unknown")


# ---- tags --------------------------------------------------------------------------------
def find_tags(client: StashClient, text: str) -> list[Tag]:
    """Autocomplete. Stash's `q` search matches names and aliases, anywhere in the text."""
    data = client.gql(q.FIND_TAGS_BY_NAME, {"q": text})
    return [t for t in (Tag.parse(x) for x in (data.get("findTags") or {}).get("tags") or []) if t]


def find_tag_exact(client: StashClient, name: str) -> Tag | None:
    """The tag called name, ignoring case; failing that, the tag that has name as an alias."""
    data = client.gql(q.FIND_TAG_EXACT, {"name": name})
    tags = [t for t in (Tag.parse(x) for x in (data.get("findTags") or {}).get("tags") or []) if t]
    key = name.lower()
    for t in tags:
        if t.name.lower() == key:
            return t
    for t in tags:
        if any(a.lower() == key for a in t.aliases):
            return t
    return None


def ensure_tag(client: StashClient, name: str) -> Tag:
    """Find-or-create, reusing an existing tag whatever its case (the owner may have made "Imaglr" by hand)."""
    tag = find_tag_exact(client, name)
    if tag:
        return tag
    try:
        data = client.gql(q.TAG_CREATE, {"name": name})
    except StashError:
        # Another operation may have created it a moment ago; Stash refuses duplicates.
        tag = find_tag_exact(client, name)
        if tag:
            return tag
        raise
    tag = Tag.parse(data.get("tagCreate"))
    if tag is None:
        raise StashError(f"could not create tag {name!r}")
    log.info(f"Created Stash tag {name}")
    return tag


def workflow_tags(client: StashClient, queue_name: str, done_name: str) -> tuple[Tag, Tag]:
    return ensure_tag(client, queue_name), ensure_tag(client, done_name)


# ---- markers -----------------------------------------------------------------------------
def queued_markers(client: StashClient, tag_id: str, limit: int = 500) -> list[Marker]:
    """Markers carrying the tag as primary or secondary tag, newest first."""
    out: list[Marker] = []
    page = 1
    while len(out) < limit:
        data = client.gql(q.FIND_QUEUED_MARKERS, {"tagId": tag_id, "page": page, "perPage": PAGE_SIZE})
        res = data.get("findSceneMarkers") or {}
        batch = [Marker.parse(m) for m in res.get("scene_markers") or []]
        out.extend(batch)
        if len(batch) < PAGE_SIZE or len(out) >= int(res.get("count") or 0):
            break
        page += 1
    return out[:limit]


def find_marker(client: StashClient, marker_id: str) -> Marker | None:
    try:
        data = client.gql(q.FIND_MARKER_BY_ID, {"id": marker_id})
    except StashError as e:
        # Unlike findScene/findImage, findSceneMarkers(ids:) errors on a missing id instead of returning nothing.
        if "not found" in str(e):
            return None
        raise
    for m in (data.get("findSceneMarkers") or {}).get("scene_markers") or []:
        if str(m.get("id")) == str(marker_id):
            return Marker.parse(m)
    return None


def marker_update(
    client: StashClient,
    marker: Marker,
    *,
    seconds: float | None = None,
    end_seconds: float | None = None,
    primary_tag_id: str | None = None,
    tag_ids: list[str] | None = None,
) -> None:
    """Every field is sent; anything not given keeps the marker's current value."""
    variables: dict[str, Any] = {
        "id": marker.id,
        "seconds": marker.seconds if seconds is None else seconds,
        "end_seconds": marker.end_seconds if end_seconds is None else end_seconds,
        "primary_tag_id": primary_tag_id or (marker.primary_tag.id if marker.primary_tag else None),
        "tag_ids": [t.id for t in marker.tags] if tag_ids is None else tag_ids,
    }
    client.gql(q.MARKER_UPDATE, variables)


def swapped_marker_tags(marker: Marker, queue_tag: Tag, done_tag: Tag) -> tuple[str, list[str]]:
    """(primary tag id, secondary tag ids) with the queue tag replaced by the done tag.
    If the queue tag was the primary tag, the done tag becomes primary (reference spec §5)."""
    secondary = [t.id for t in marker.tags if t.id not in (queue_tag.id, done_tag.id)]
    if marker.primary_tag and marker.primary_tag.id == queue_tag.id:
        return done_tag.id, secondary
    primary = marker.primary_tag.id if marker.primary_tag else done_tag.id
    if primary != done_tag.id:
        secondary.append(done_tag.id)
    return primary, secondary


def marker_remove_tag(client: StashClient, marker: Marker, tag: Tag) -> bool:
    """Take a tag off a marker. A marker must keep a primary tag, so if the tag is primary the first
    secondary tag takes its place; returns False (and changes nothing) when it is the marker's only tag."""
    secondary = [t.id for t in marker.tags if t.id != tag.id]
    if marker.primary_tag and marker.primary_tag.id == tag.id:
        if not secondary:
            return False
        marker_update(client, marker, primary_tag_id=secondary[0], tag_ids=secondary[1:])
        return True
    if tag.id not in {t.id for t in marker.tags}:
        return True
    marker_update(client, marker, tag_ids=secondary)
    return True


def marker_swap_tags(client: StashClient, marker: Marker, queue_tag: Tag, done_tag: Tag) -> None:
    primary, secondary = swapped_marker_tags(marker, queue_tag, done_tag)
    marker_update(client, marker, primary_tag_id=primary, tag_ids=secondary)


# ---- images ------------------------------------------------------------------------------
def queued_images(client: StashClient, tag_id: str, limit: int = 1000) -> list[Image]:
    out: list[Image] = []
    page = 1
    while len(out) < limit:
        data = client.gql(q.FIND_QUEUED_IMAGES, {"tagId": tag_id, "page": page, "perPage": PAGE_SIZE})
        res = data.get("findImages") or {}
        batch = [Image.parse(i) for i in res.get("images") or []]
        out.extend(batch)
        if len(batch) < PAGE_SIZE or len(out) >= int(res.get("count") or 0):
            break
        page += 1
    return out[:limit]


def find_image(client: StashClient, image_id: str) -> Image | None:
    d = client.gql(q.FIND_IMAGE_BY_ID, {"id": image_id}).get("findImage")
    return Image.parse(d) if d else None


def images_add_tags(client: StashClient, image_ids: list[str], tag_ids: list[str]) -> None:
    client.gql(q.BULK_IMAGE_ADD_TAGS, {"ids": image_ids, "add": tag_ids})


def images_remove_tags(client: StashClient, image_ids: list[str], tag_ids: list[str]) -> None:
    client.gql(q.BULK_IMAGE_REMOVE_TAGS, {"ids": image_ids, "remove": tag_ids})


def image_swap_tags(client: StashClient, image_id: str, queue_tag: Tag, done_tag: Tag) -> None:
    """Add the done tag first, so a failure half-way never leaves the image with neither tag."""
    images_add_tags(client, [image_id], [done_tag.id])
    images_remove_tags(client, [image_id], [queue_tag.id])


# ---- scenes ------------------------------------------------------------------------------
def find_scenes(client: StashClient, text: str, page: int = 1, per_page: int = 20) -> tuple[int, list[Scene]]:
    data = client.gql(q.FIND_SCENES, {"q": text, "page": page, "perPage": per_page})
    res = data.get("findScenes") or {}
    return int(res.get("count") or 0), [Scene.parse(s) for s in res.get("scenes") or []]


def find_scene(client: StashClient, scene_id: str) -> Scene | None:
    d = client.gql(q.FIND_SCENE_BY_ID, {"id": scene_id}).get("findScene")
    return Scene.parse(d) if d else None


# ---- media over HTTP ---------------------------------------------------------------------
def auth_headers(client: StashClient) -> dict[str, str]:
    """Headers that authenticate a plain HTTP request to Stash, the same way client.gql does."""
    return client.auth_headers()


def download(client: StashClient, url: str, dest: str) -> str:
    """Fetch a Stash media URL (image `paths.image`, scene `paths.stream`) to dest. Returns its Content-Type."""
    return paths.fetch(url, dest, auth_headers(client), client.timeout, client.ssl_context)


def generate_marker_previews(client: StashClient, scene_id: str) -> str | None:
    """Ask Stash to make marker screenshots and previews for a scene (a normal Stash Generate job).

    By scene, not by marker: Stash v0.31.1 only creates the scene's marker folder when generating
    by scene, so generating a single new marker fails if its scene had none before.
    """
    data = client.gql(q.GENERATE_MARKER_PREVIEWS, {"ids": [scene_id]})
    return data.get("metadataGenerate")

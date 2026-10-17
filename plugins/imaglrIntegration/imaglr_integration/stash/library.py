# SPDX-License-Identifier: AGPL-3.0-only
"""What saving from imaglr asks of Stash: its library folders and scan defaults, scanning saved files in, finding
them again by path or by the imaglr post they came from, writing the credit onto them, grouping a post's files
as a gallery, and matching imaglr tags to Stash tags, performers and studios by name or alias."""

from __future__ import annotations

from typing import Any

from .. import saving
from .client import StashClient

LIBRARY = """
{ configuration {
    general { stashes { path excludeVideo excludeImage } }
    defaults { scan { scanGenerateCovers scanGeneratePreviews scanGenerateImagePreviews scanGenerateSprites
                      scanGeneratePhashes scanGenerateImagePhashes scanGenerateThumbnails scanGenerateClipPreviews } }
} }
"""
SCAN = "mutation($input: ScanMetadataInput!) { metadataScan(input: $input) }"
# What a scan generates when the user has never saved scan defaults in Stash: a cover for a video, a thumbnail
# for a picture, so saved items look right in Stash's lists.
FALLBACK_SCAN = {"scanGenerateCovers": True, "scanGenerateThumbnails": True}

SAVED_BY_POST = """
query($f: [CustomFieldCriterionInput!]) {
  findScenes(scene_filter: { custom_fields: $f }, filter: { per_page: 200 }) { scenes { id custom_fields } }
  findImages(image_filter: { custom_fields: $f }, filter: { per_page: 200 }) { images { id custom_fields } }
  findGalleries(gallery_filter: { custom_fields: $f }, filter: { per_page: 200 }) { galleries { id custom_fields } }
}
"""
SCENE_BY_PATH = "query($p: String!) { findScenes(scene_filter: { path: { value: $p, modifier: EQUALS } }) { scenes { id files { path } } } }"
IMAGE_BY_PATH = """
query($p: String!) { findImages(image_filter: { path: { value: $p, modifier: EQUALS } }) {
  images { id visual_files { ... on ImageFile { path } ... on VideoFile { path } } } } }
"""
SCENE_UPDATE = "mutation($input: SceneUpdateInput!) { sceneUpdate(input: $input) { id } }"
IMAGE_UPDATE = "mutation($input: ImageUpdateInput!) { imageUpdate(input: $input) { id } }"
GALLERY_CREATE = "mutation($input: GalleryCreateInput!) { galleryCreate(input: $input) { id } }"
GALLERY_ADD_IMAGES = "mutation($input: GalleryAddInput!) { addGalleryImages(input: $input) }"
NAMES = """
query($r: String!) {
  findTags(tag_filter: { name: { value: $r, modifier: MATCHES_REGEX }, OR: { aliases: { value: $r, modifier: MATCHES_REGEX } } },
           filter: { per_page: 200 }) { tags { id name aliases } }
  findPerformers(performer_filter: { name: { value: $r, modifier: MATCHES_REGEX }, OR: { aliases: { value: $r, modifier: MATCHES_REGEX } } },
                 filter: { per_page: 200 }) { performers { id name alias_list } }
  findStudios(studio_filter: { name: { value: $r, modifier: MATCHES_REGEX }, OR: { aliases: { value: $r, modifier: MATCHES_REGEX } } },
              filter: { per_page: 200 }) { studios { id name aliases } }
}
"""
FINDERS = {"tag": "findTag", "performer": "findPerformer", "studio": "findStudio"}  # null when gone, unlike the lists
SEARCH = """
query($q: String!) {
  findTags(filter: { q: $q, per_page: 8, sort: "name" }) { tags { id name } }
  findPerformers(filter: { q: $q, per_page: 8, sort: "name" }) { performers { id name } }
  findStudios(filter: { q: $q, per_page: 8, sort: "name" }) { studios { id name } }
}
"""
PLUGIN_CONFIG = "query($id: ID!) { configuration { plugins(include: [$id]) } }"
CONFIGURE_PLUGIN = "mutation($id: ID!, $input: Map!) { configurePlugin(plugin_id: $id, input: $input) }"


def libraries(client: StashClient) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    """Stash's library folders, and the options a scan of saved files uses (the user's own scan defaults)."""
    config = client.gql(LIBRARY)["configuration"]
    libs = [lib for lib in (config["general"]["stashes"] or []) if lib and lib.get("path")]
    defaults = (config.get("defaults") or {}).get("scan")
    options = {k: bool(v) for k, v in defaults.items()} if isinstance(defaults, dict) else dict(FALLBACK_SCAN)
    return libs, options


def scan(client: StashClient, paths: list[str], options: dict[str, bool]) -> str:
    """Queue a Stash scan of just these files (it runs after the current task); returns the job id."""
    return str(client.gql(SCAN, {"input": {"paths": paths, **options}})["metadataScan"])


def saved_refs(client: StashClient, post_ids: list[str]) -> dict[str, list[dict[str, str]]]:
    """For each imaglr post id, the Stash scenes, images and galleries saved from it."""
    ids = sorted({str(p) for p in post_ids if p})
    out: dict[str, list[dict[str, str]]] = {p: [] for p in ids}
    if not ids:
        return out
    criterion = [{"field": saving.CUSTOM_POST_ID, "modifier": "MATCHES_REGEX", "value": [saving.regex_any(ids)]}]
    data = client.gql(SAVED_BY_POST, {"f": criterion})
    for kind, key, inner in (("scene", "findScenes", "scenes"), ("image", "findImages", "images"),
                             ("gallery", "findGalleries", "galleries")):
        for obj in data[key][inner]:
            post_id = str((obj.get("custom_fields") or {}).get(saving.CUSTOM_POST_ID) or "")
            if post_id in out:
                out[post_id].append({"kind": kind, "id": str(obj["id"])})
    return out


def find_by_path(client: StashClient, path: str) -> dict[str, str] | None:
    """The scene or image Stash made from this file, if it has."""
    for query, key, inner, kind in ((IMAGE_BY_PATH, "findImages", "images", "image"),
                                    (SCENE_BY_PATH, "findScenes", "scenes", "scene")):
        found = client.gql(query, {"p": path})[key][inner]
        if found:
            return {"kind": kind, "id": str(found[0]["id"])}
    return None


def apply_credit(client: StashClient, ref: dict[str, str], fields: dict[str, Any]) -> None:
    """Write the credit, tags, performers and studio onto a saved scene or image."""
    query = SCENE_UPDATE if ref["kind"] == "scene" else IMAGE_UPDATE
    client.gql(query, {"input": {"id": ref["id"], **fields}})


def create_gallery(client: StashClient, fields: dict[str, Any], image_ids: list[str]) -> str:
    """A gallery for a post with several files, carrying the same credit, holding its pictures."""
    gallery_id = str(client.gql(GALLERY_CREATE, {"input": fields})["galleryCreate"]["id"])
    if image_ids:
        client.gql(GALLERY_ADD_IMAGES, {"input": {"gallery_id": gallery_id, "image_ids": image_ids}})
    return gallery_id


def name_candidates(client: StashClient, imaglr_tags: list[str]) -> dict[str, list[dict[str, Any]]]:
    """The Stash tags, performers and studios whose name or one of whose aliases could equal one of these imaglr
    tags (one query; import_rules.plan decides exactly)."""
    tags = [t for t in dict.fromkeys(imaglr_tags) if t.strip()]
    if not tags:
        return {"tag": [], "performer": [], "studio": []}
    data = client.gql(NAMES, {"r": saving.regex_any(tags)})
    return {
        "tag": data["findTags"]["tags"],
        "performer": [{"id": p["id"], "name": p["name"], "aliases": p.get("alias_list") or []} for p in data["findPerformers"]["performers"]],
        "studio": data["findStudios"]["studios"],
    }


def match_names(client: StashClient, imaglr_tags: list[str], exclude: set[str]) -> dict[str, Any]:
    """Stash tags, performers and a studio whose name or alias equals one of the post's imaglr tags."""
    tags = [t for t in dict.fromkeys(imaglr_tags) if t.strip()]
    found = name_candidates(client, tags)
    studios = saving.matches(tags, found["studio"], exclude)
    return {
        "tag_ids": saving.matches(tags, found["tag"], exclude),
        "performer_ids": saving.matches(tags, found["performer"], exclude),
        "studio_id": studios[0] if len(studios) == 1 else None,  # two studios match: name neither
    }


def existing(client: StashClient, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The targets that still exist in Stash, with their current names (a remembered rule may point at a tag,
    performer or studio deleted since)."""
    wanted = [t for t in targets if t.get("kind") in FINDERS and str(t.get("id") or "").isdigit()]
    if not wanted:
        return []
    # One query, one aliased single-item lookup per target: the list finders fail outright on a missing id.
    parts = [f'x{n}: {FINDERS[t["kind"]]}(id: "{t["id"]}") {{ id name }}' for n, t in enumerate(wanted)]
    data = client.gql("{ " + " ".join(parts) + " }")
    return [{**t, "name": data[f"x{n}"]["name"]} for n, t in enumerate(wanted) if data.get(f"x{n}")]


def search(client: StashClient, text: str) -> list[dict[str, str]]:
    """Stash tags, performers and studios whose name or alias contains the text, for choosing in the review."""
    if not text.strip():
        return []
    data = client.gql(SEARCH, {"q": text.strip()})
    out = [{"kind": "tag", "id": str(x["id"]), "name": x["name"]} for x in data["findTags"]["tags"]]
    out += [{"kind": "performer", "id": str(x["id"]), "name": x["name"]} for x in data["findPerformers"]["performers"]]
    out += [{"kind": "studio", "id": str(x["id"]), "name": x["name"]} for x in data["findStudios"]["studios"]]
    return out


def plugin_config(client: StashClient, plugin_id: str) -> dict[str, Any]:
    return dict((client.gql(PLUGIN_CONFIG, {"id": plugin_id})["configuration"]["plugins"] or {}).get(plugin_id) or {})


def set_plugin_config(client: StashClient, plugin_id: str, values: dict[str, Any]) -> None:
    """Change some of the plugin's Stash settings, keeping the rest (Stash replaces the whole set)."""
    merged = {**plugin_config(client, plugin_id), **values}
    client.gql(CONFIGURE_PLUGIN, {"id": plugin_id, "input": merged})

# SPDX-License-Identifier: AGPL-3.0-only
"""Saving imaglr posts the user chooses into their Stash library: what a post looks like to the UI, who it is
credited to, where its files go, and what Stash is told about it. Pure functions; the operations that use them
are in browse_ops.

Credit lives where it survives the plugin being uninstalled: in Stash's own fields (the post's and creator's
links, a credit line in the details, the post date, and two custom fields that let the plugin find the post
again) and in the file's path (creator folder, post id as the file name). The creator is never made a
performer, studio or tag.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

CUSTOM_POST_ID = "imaglr_post_id"  # Stash custom field: the imaglr post a saved file came from
CUSTOM_CREATOR = "imaglr_creator"  # Stash custom field: who posted it on imaglr
MEDIA_KINDS = ("image", "video")
EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}
# Larger than imaglr's own upload ceilings (40 MB a picture, 500 MB a video), so nothing real is refused.
MAX_BYTES = {"image": 64 * 1024 * 1024, "video": 600 * 1024 * 1024}
TITLE_MAX = 120


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _url(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith(("https://", "http://")) else None


def profile_view(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {"name": _text(raw.get("name")), "url": _url(raw.get("url")), "avatar": _url(raw.get("avatar"))}


def creator_view(raw: Any) -> dict[str, Any]:
    """A creator's profile for the header of their page: who they are, their bio (plain text) and counts."""
    raw = raw if isinstance(raw, dict) else {}
    counts = raw.get("counts") if isinstance(raw.get("counts"), dict) else {}
    return {**profile_view(raw), "description": _text(raw.get("description")),
            "counts": {k: _int(counts.get(k)) or 0 for k in ("followers", "following", "posts")}}


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def normalize_post(raw: dict[str, Any]) -> dict[str, Any]:
    """An imaglr post as the browse view uses it: only the fields it needs, every one checked, and only the
    pictures and videos among its media (text, links, polls and audio are shown as text or not at all)."""
    media = []
    for m in raw.get("media") or []:
        if not isinstance(m, dict) or m.get("kind") not in MEDIA_KINDS or not _url(m.get("url")):
            continue
        media.append({"kind": m["kind"], "url": m["url"], "thumb": _url(m.get("thumb")), "mime": _text(m.get("mime")) or None,
                      "width": _int(m.get("width")), "height": _int(m.get("height"))})
    original = None
    source = raw.get("reposted_from")
    if isinstance(source, dict) and source.get("id") is not None:
        original = {"id": str(source["id"]), "url": _url(source.get("url")), "creator": profile_view(source.get("profile"))}
    tags = []
    for t in raw.get("tags") or []:
        name = t if isinstance(t, str) else t.get("name") if isinstance(t, dict) else None
        if isinstance(name, str) and name.strip():
            tags.append(name.strip())
    notes = raw.get("note_count") if isinstance(raw.get("note_count"), dict) else {}
    return {
        "id": str(raw["id"]),
        "url": _url(raw.get("url")),
        "type": _text(raw.get("type")),
        "created_at": _text(raw.get("created_at")) or None,
        "summary": _text(raw.get("summary")),
        "tags": tags,
        "nsfw": bool(raw.get("nsfw")),
        "creator": profile_view(raw.get("profile")),
        "original": original,
        "media": media,
        "notes": {k: _int(notes.get(k)) or 0 for k in ("likes", "reposts", "comments")},
        "liked": bool(raw.get("liked")),
    }


def credit(post: dict[str, Any]) -> dict[str, Any]:
    """Who a saved post is credited to: the original post and its creator when it is a reblog (imaglr serves
    the original's media for a reblog anyway), otherwise the post itself."""
    original = post.get("original")
    if original and original.get("id"):
        creator = original["creator"] if original["creator"].get("name") else post["creator"]
        return {"id": original["id"], "url": original.get("url") or post.get("url"), "creator": creator}
    return {"id": post["id"], "url": post.get("url"), "creator": post["creator"]}


def safe_name(text: str, fallback: str = "imaglr") -> str:
    """A folder or file name that is valid on Windows, macOS and Linux."""
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text).strip(" ._")
    return text[:80] or fallback


def extension(media: dict[str, Any]) -> str:
    """The file extension for a media file: from its type, else from its address, else by kind."""
    ext = EXTENSIONS.get((media.get("mime") or "").lower())
    if ext:
        return ext
    path_ext = os.path.splitext(media["url"].split("?", 1)[0])[1].lower()
    if path_ext in EXTENSIONS.values() or path_ext == ".jpeg":
        return ".jpg" if path_ext == ".jpeg" else path_ext
    return ".mp4" if media["kind"] == "video" else ".jpg"


def file_plan(folder: str, post: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Where each of a post's files is saved: <folder>/<creator>/<post id>.<ext>, numbered from -1 when the
    post has several files. The credited (original) post and creator name the path."""
    who = credit(post)
    where = os.path.join(folder, safe_name(who["creator"]["name"], "unknown"))
    media = post["media"]
    out = []
    for n, m in enumerate(media, start=1):
        stem = who["id"] if len(media) == 1 else f"{who['id']}-{n}"
        out.append((m, os.path.join(where, safe_name(stem) + extension(m))))
    return out


def title_text(post: dict[str, Any]) -> str:
    """The Stash title: the caption's first line, else who posted it."""
    first = (post.get("summary") or "").strip().splitlines()
    line = first[0].strip() if first else ""
    if len(line) > TITLE_MAX:
        line = line[: TITLE_MAX - 1].rstrip() + "…"
    if line:
        return line
    name = credit(post)["creator"]["name"]
    return f"@{name} on imaglr" if name else "imaglr post"


def details_text(post: dict[str, Any]) -> str:
    """The Stash details: a credit line, then the caption."""
    who = credit(post)
    name = who["creator"]["name"]
    line = "Saved from imaglr"
    if name:
        line += f". Posted by @{name}"
    date = (post.get("created_at") or "")[:10]
    if date and not post.get("original"):
        line += f" on {date}"
    line += "."
    if who.get("url"):
        line += f"\n{who['url']}"
    caption = (post.get("summary") or "").strip()
    return f"{line}\n\n{caption}" if caption else line


def stash_date(post: dict[str, Any]) -> str | None:
    date = (post.get("created_at") or "")[:10]
    return date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else None


def stash_urls(post: dict[str, Any]) -> list[str]:
    """The post's link first, then the creator's profile."""
    who = credit(post)
    return [u for u in (who.get("url"), who["creator"].get("url")) if u]


def custom_fields(post: dict[str, Any]) -> dict[str, str]:
    who = credit(post)
    fields = {CUSTOM_POST_ID: who["id"]}
    if who["creator"]["name"]:
        fields[CUSTOM_CREATOR] = who["creator"]["name"]
    return fields


def regex_any(values: list[str]) -> str:
    """A case-insensitive whole-value pattern matching any of `values`, in the syntax Stash's filters use
    (Go's RE2): every punctuation character escaped."""
    escaped = ["".join("\\" + c if not c.isalnum() and not c.isspace() and c != "_" and ord(c) < 128 else c for c in v)
               for v in values]
    return "(?i)^(?:" + "|".join(escaped) + ")$"


def matches(imaglr_tags: list[str], candidates: list[dict[str, Any]], exclude: set[str] = frozenset()) -> list[str]:
    """Ids of the Stash objects whose name or one of whose aliases equals one of the imaglr tags, ignoring case.
    Whole names only: "amber" matches a performer called Amber, never Amber Rose. `exclude` holds names (lower
    case) never to match, such as the plugin's own queue and sent tags."""
    wanted = {t.casefold() for t in imaglr_tags}
    out = []
    for c in candidates:
        names = [c.get("name") or ""] + [a for a in c.get("aliases") or [] if isinstance(a, str)]
        folded = {n.casefold() for n in names if n}
        if folded & exclude:
            continue
        if folded & wanted and c["id"] not in out:
            out.append(c["id"])
    return out


def inside(path: str, root: str) -> bool:
    """True when `path` is `root` or a folder or file below it."""
    try:
        path, root = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))
        return os.path.commonpath([path, root]) == root
    except ValueError:  # different drives on Windows
        return False


def library_for(folder: str, libraries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The Stash library a folder sits in (the deepest, if they nest), or None."""
    found = [lib for lib in libraries if lib.get("path") and inside(folder, lib["path"])]
    return max(found, key=lambda lib: len(lib["path"])) if found else None

# SPDX-License-Identifier: AGPL-3.0-only
"""imaglr blogs: one API key per blog, stored only in the plugin database.

Keys never leave the backend once saved: everything returned to the UI goes through `public()`,
which shows the key masked.
"""

from __future__ import annotations

from typing import Any

from .db import Database, now_iso

ACTIONS = ("draft", "queue", "publish")


class BlogError(ValueError):
    pass


def mask_key(key: str) -> str:
    return f"pbk_…{key[-4:]}" if len(key) > 8 else "pbk_…"


def public(blog: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in blog.items() if k != "api_key"}
    out["key_hint"] = mask_key(blog["api_key"])
    for key in ("supporter", "nsfw"):
        out[key] = None if blog[key] is None else bool(blog[key])
    out["ok"] = bool(blog["ok"])
    out["label"] = blog["name"] or f"Blog {blog['id']} (not checked yet)"
    return out


def list_blogs(db: Database) -> list[dict[str, Any]]:
    return db.fetchall("SELECT * FROM blogs ORDER BY position, id")


def get_blog(db: Database, blog_id: int) -> dict[str, Any] | None:
    return db.fetchone("SELECT * FROM blogs WHERE id=?", (blog_id,))


def add_blog(db: Database, api_key: str, default_action: str = "draft") -> dict[str, Any]:
    api_key = api_key.strip()
    if not api_key.startswith("pbk_") or len(api_key) < 10 or any(c.isspace() for c in api_key):
        raise BlogError("That doesn't look like an imaglr API key (they start with pbk_).")
    if default_action not in ACTIONS:
        raise BlogError(f"Unknown send action: {default_action}")
    if db.fetchone("SELECT id FROM blogs WHERE api_key=?", (api_key,)):
        raise BlogError("That key has already been added.")
    position = (db.fetchone("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM blogs") or {"p": 0})["p"]
    cur = db.execute(
        "INSERT INTO blogs(api_key, default_action, position, created_at) VALUES(?, ?, ?, ?)",
        (api_key, default_action, position, now_iso()),
    )
    return get_blog(db, cur.lastrowid)  # type: ignore[return-value]


def remove_blog(db: Database, blog_id: int) -> None:
    db.execute("DELETE FROM blogs WHERE id=?", (blog_id,))


def set_default_action(db: Database, blog_id: int, action: str) -> None:
    if action not in ACTIONS:
        raise BlogError(f"Unknown send action: {action}")
    db.execute("UPDATE blogs SET default_action=? WHERE id=?", (action, blog_id))


def record_check(db: Database, blog_id: int, profile: dict[str, Any] | None, error: tuple[str, str] | None) -> None:
    """Store the result of GET /user/info for a blog: its profile, or (error code, detail)."""
    if profile is not None:
        db.execute(
            "UPDATE blogs SET name=?, url=?, supporter=?, nsfw=?, ok=1, error_code=NULL, error_detail=NULL, "
            "checked_at=? WHERE id=?",
            (profile.get("name"), profile.get("url"), _flag(profile.get("supporter")), _flag(profile.get("nsfw")),
             now_iso(), blog_id),
        )
    else:
        code, detail = error or ("unknown", "")
        db.execute(
            "UPDATE blogs SET ok=0, error_code=?, error_detail=?, checked_at=? WHERE id=?",
            (code, detail, now_iso(), blog_id),
        )


def set_paused(db: Database, blog_id: int, reason: str | None) -> None:
    db.execute("UPDATE blogs SET paused_reason=? WHERE id=?", (reason, blog_id))


def resolve_action(blog: dict[str, Any], item_action: str | None) -> str:
    """The item's own choice at send time wins; otherwise the blog's default."""
    return item_action if item_action in ACTIONS else blog["default_action"]


def _flag(value: Any) -> int | None:
    return None if value is None else int(bool(value))

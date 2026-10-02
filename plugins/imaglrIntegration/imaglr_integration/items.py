# SPDX-License-Identifier: AGPL-3.0-only
"""Item repository: edits, job state and send history. Stash stays the source of truth for what is queued."""

from __future__ import annotations

import json
import uuid
from typing import Any

from .db import Database, loads, now_iso

ACTIVE_STATUSES = ("pending", "exporting", "ready", "sending", "failed")
IN_FLIGHT_STATUSES = ("exporting", "sending")
JSON_FIELDS = {"crop", "tags", "dropped_tags"}
BOOL_FIELDS = ("mute", "flip", "hdr_warning", "cancel_requested", "followup_failed", "size_guard_retried",
               "tags_auto", "tags_pending")
DEFAULT_CROP = {"aspect": "original", "position": 0.5}
MAX_SET_MEMBERS = 10


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _enc(key: str, value: Any) -> Any:
    if key in JSON_FIELDS:
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value


def decode(row: dict[str, Any]) -> dict[str, Any]:
    row["crop"] = loads(row.get("crop"), dict(DEFAULT_CROP))
    row["tags"] = loads(row.get("tags"), [])
    row["dropped_tags"] = loads(row.get("dropped_tags"), [])
    for key in BOOL_FIELDS:
        row[key] = bool(row.get(key))
    return row


def create_item(db: Database, **fields: Any) -> dict[str, Any]:
    fields.setdefault("id", new_id())
    fields.setdefault("status", "pending")
    fields.setdefault("crop", dict(DEFAULT_CROP))
    fields.setdefault("tags", [])
    fields.setdefault("dropped_tags", [])
    ts = now_iso()
    fields.setdefault("created_at", ts)
    fields.setdefault("updated_at", ts)
    cols = list(fields)
    db.execute(
        f"INSERT INTO items ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        tuple(_enc(k, fields[k]) for k in cols),
    )
    return get_item(db, fields["id"])  # type: ignore[return-value]


def get_item(db: Database, item_id: str) -> dict[str, Any] | None:
    row = db.fetchone("SELECT * FROM items WHERE id=?", (item_id,))
    return decode(row) if row else None


def update_item(db: Database, item_id: str, **fields: Any) -> dict[str, Any] | None:
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k}=?" for k in fields)
    db.execute(f"UPDATE items SET {sets} WHERE id=?", tuple(_enc(k, v) for k, v in fields.items()) + (item_id,))
    return get_item(db, item_id)


def delete_item(db: Database, item_id: str) -> None:
    db.execute("DELETE FROM items WHERE id=?", (item_id,))


def list_items(
    db: Database,
    statuses: tuple[str, ...] | None = None,
    kinds: tuple[str, ...] | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where, params = [], []  # type: ignore[var-annotated]
    if statuses:
        where.append(f"status IN ({','.join('?' for _ in statuses)})")
        params.extend(statuses)
    if kinds:
        where.append(f"kind IN ({','.join('?' for _ in kinds)})")
        params.extend(kinds)
    sql = "SELECT * FROM items"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC, created_at DESC LIMIT ? OFFSET ?"
    return [decode(r) for r in db.fetchall(sql, tuple(params + [limit, offset]))]


def active_for_marker(db: Database, marker_id: str) -> dict[str, Any] | None:
    row = db.fetchone(
        "SELECT * FROM items WHERE stash_marker_id=? AND status!='sent' ORDER BY created_at DESC LIMIT 1",
        (marker_id,),
    )
    return decode(row) if row else None


def sent_with_pending_swap(db: Database, *, marker_id: str | None = None, image_id: str | None = None) -> dict[str, Any] | None:
    """A sent item for this source whose Stash tags never got swapped (the swap failed or the task died)."""
    column, value = ("stash_marker_id", marker_id) if marker_id else ("stash_image_id", image_id)
    row = db.fetchone(f"SELECT * FROM items WHERE {column}=? AND status='sent' AND tags_pending=1 ORDER BY created_at DESC LIMIT 1", (value,))
    return decode(row) if row else None


def active_for_image(db: Database, image_id: str) -> dict[str, Any] | None:
    row = db.fetchone(
        "SELECT * FROM items WHERE stash_image_id=? AND status!='sent' ORDER BY created_at DESC LIMIT 1",
        (image_id,),
    )
    return decode(row) if row else None


def bump_used_tags(db: Database, tags: list[str]) -> None:
    ts = now_iso()
    for tag in tags:
        db.execute(
            "INSERT INTO used_tags(tag, use_count, last_used) VALUES(?, 1, ?) "
            "ON CONFLICT(tag) DO UPDATE SET use_count=use_count+1, last_used=excluded.last_used",
            (tag, ts),
        )


def tag_mapping(db: Database) -> dict[str, list[str]]:
    """Tag rules: lower-cased Stash tag -> the imaglr tags to send instead ([] = never suggest)."""
    return {r["stash_tag"].lower(): loads(r["imaglr_tags"], []) for r in db.fetchall("SELECT * FROM tag_rules")}


# ---- sets --------------------------------------------------------------------------------


def set_members(db: Database, set_id: str) -> list[dict[str, Any]]:
    rows = db.fetchall(
        "SELECT i.* FROM set_members m JOIN items i ON i.id = m.item_id WHERE m.set_id=? ORDER BY m.position",
        (set_id,),
    )
    return [decode(r) for r in rows]


def set_of(db: Database, item_id: str) -> str | None:
    row = db.fetchone("SELECT set_id FROM set_members WHERE item_id=?", (item_id,))
    return row["set_id"] if row else None


def members_index(db: Database) -> dict[str, str]:
    """item_id -> set_id for every item that belongs to a set."""
    return {r["item_id"]: r["set_id"] for r in db.fetchall("SELECT item_id, set_id FROM set_members")}


def set_member_ids(db: Database, set_id: str, item_ids: list[str]) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM set_members WHERE set_id=?", (set_id,))
        conn.executemany(
            "INSERT INTO set_members(set_id, item_id, position) VALUES(?, ?, ?)",
            [(set_id, item_id, n) for n, item_id in enumerate(item_ids)],
        )
    update_item(db, set_id)

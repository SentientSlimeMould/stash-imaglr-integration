# SPDX-License-Identifier: AGPL-3.0-only
"""Deleting prepared files (data/prepared/<item id>/) the plugin no longer needs.

Runs when the Post to imaglr page loads and after each send, so no scheduler is needed.
"""

from __future__ import annotations

import os
import shutil
import time
from datetime import datetime, timedelta, timezone

from . import log
from .db import Database

ORPHAN_GRACE_SECONDS = 3600  # a folder may briefly exist before its item row is committed


def cleanup_prepared(db: Database, prepared_root: str, retention_days: int, now: datetime | None = None) -> int:
    """Remove prepared files of items sent (or failed) more than `retention_days` ago, and folders whose
    item no longer exists. A failed still keeps its grabbed frame, which is its only source.
    Returns the number of folders removed."""
    if not os.path.isdir(prepared_root):
        return 0
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=max(0, retention_days))).isoformat(timespec="seconds")
    rows = db.fetchall(
        "SELECT id FROM items WHERE (status='sent' AND COALESCE(sent_at, updated_at) < ?) "
        "OR (status='failed' AND kind!='still' AND updated_at < ?)",
        (cutoff, cutoff),
    )
    removed = 0
    for row in rows:
        folder = os.path.join(prepared_root, row["id"])
        if os.path.isdir(folder):
            removed += _remove(folder)
        db.execute("UPDATE items SET output_path=NULL, output_bytes=NULL, source_path=NULL WHERE id=?", (row["id"],))

    known = {r["id"] for r in db.fetchall("SELECT id FROM items")}
    for name in os.listdir(prepared_root):
        folder = os.path.join(prepared_root, name)
        if name not in known and os.path.isdir(folder) and time.time() - os.path.getmtime(folder) > ORPHAN_GRACE_SECONDS:
            removed += _remove(folder)
    if removed:
        log.info(f"removed {removed} prepared folder(s)")
    return removed


def _remove(folder: str) -> int:
    try:
        shutil.rmtree(folder)
        return 1
    except OSError as e:
        log.warning(f"could not remove {folder}: {e}")
        return 0

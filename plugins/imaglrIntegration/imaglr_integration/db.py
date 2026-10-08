# SPDX-License-Identifier: AGPL-3.0-only
"""The plugin's own SQLite database, in <plugin dir>/data/imaglr.sqlite.

Every plugin call is a short-lived process, and operations run concurrently with tasks, so each
process opens its own connection: WAL mode plus a busy timeout. Migrations are forward-only and
run on open.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

DB_NAME = "imaglr.sqlite"

MIGRATIONS = [
    """
    CREATE TABLE items (
      id TEXT PRIMARY KEY,
      kind TEXT NOT NULL CHECK (kind IN ('clip','image','still','set')),
      stash_scene_id TEXT,
      stash_marker_id TEXT,
      stash_image_id TEXT,
      source_item_id TEXT REFERENCES items(id) ON DELETE SET NULL,
      source_title TEXT NOT NULL DEFAULT '',
      in_s REAL,
      out_s REAL,
      still_t REAL,
      crop TEXT NOT NULL DEFAULT '{"aspect":"original","position":0.5}',
      mute INTEGER NOT NULL DEFAULT 0,
      caption TEXT NOT NULL DEFAULT '',
      tags TEXT NOT NULL DEFAULT '[]',
      dropped_tags TEXT NOT NULL DEFAULT '[]',
      blog_id INTEGER REFERENCES blogs(id) ON DELETE SET NULL,
      action TEXT CHECK (action IN ('draft','queue','publish')),
      status TEXT NOT NULL CHECK (status IN ('pending','exporting','ready','sending','sent','failed')),
      progress REAL NOT NULL DEFAULT 0,
      stash_job_id TEXT,
      cancel_requested INTEGER NOT NULL DEFAULT 0,
      output_path TEXT,
      output_bytes INTEGER,
      output_mime TEXT,
      size_guard_retried INTEGER NOT NULL DEFAULT 0,
      hdr_warning INTEGER NOT NULL DEFAULT 0,
      draft_id TEXT,
      post_url TEXT,
      sent_as TEXT CHECK (sent_as IN ('draft','queue','publish')),
      sent_at TEXT,
      followup_failed INTEGER NOT NULL DEFAULT 0,
      error_code TEXT,
      error_detail TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX items_status_idx ON items(status, updated_at);
    CREATE INDEX items_marker_idx ON items(stash_marker_id);
    CREATE INDEX items_image_idx ON items(stash_image_id);

    CREATE TABLE set_members (
      set_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
      item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
      position INTEGER NOT NULL,
      PRIMARY KEY (set_id, item_id)
    );
    CREATE UNIQUE INDEX set_members_item_idx ON set_members(item_id);

    CREATE TABLE blogs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      api_key TEXT NOT NULL UNIQUE,
      name TEXT,
      url TEXT,
      supporter INTEGER,
      nsfw INTEGER,
      default_action TEXT NOT NULL DEFAULT 'draft' CHECK (default_action IN ('draft','queue','publish')),
      position INTEGER NOT NULL DEFAULT 0,
      ok INTEGER NOT NULL DEFAULT 0,
      error_code TEXT,
      error_detail TEXT,
      paused_reason TEXT,
      checked_at TEXT,
      created_at TEXT NOT NULL
    );

    CREATE TABLE tag_map (
      stash_tag TEXT PRIMARY KEY COLLATE NOCASE,
      imaglr_tag TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE used_tags (
      tag TEXT PRIMARY KEY COLLATE NOCASE,
      use_count INTEGER NOT NULL DEFAULT 0,
      last_used TEXT NOT NULL
    );

    CREATE TABLE queue_seen (key TEXT PRIMARY KEY, first_seen TEXT NOT NULL);

    CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
    # v2: stills keep the frame grabbed from their clip
    """
    ALTER TABLE items ADD COLUMN source_path TEXT;
    """,
    # v3: a tag rule maps one Stash tag to a list of imaglr tags (JSON; [] = never suggest)
    """
    CREATE TABLE tag_rules (
      stash_tag TEXT PRIMARY KEY COLLATE NOCASE,
      imaglr_tags TEXT NOT NULL DEFAULT '[]',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    INSERT INTO tag_rules(stash_tag, imaglr_tags, created_at, updated_at)
      SELECT stash_tag,
             CASE WHEN imaglr_tag IS NULL THEN '[]'
                  ELSE '["' || replace(replace(imaglr_tag, '\\', '\\\\'), '"', '\\"') || '"]' END,
             created_at, updated_at
      FROM tag_map;
    DROP TABLE tag_map;
    """,
    # v4: an item's tags follow its Stash tags and the tag rules until the user edits them
    """
    ALTER TABLE items ADD COLUMN tags_auto INTEGER NOT NULL DEFAULT 1;
    """,
    # v5: a sent item whose Stash tag swap (queue tag -> sent tag) still has to be done
    """
    ALTER TABLE items ADD COLUMN tags_pending INTEGER NOT NULL DEFAULT 0;
    """,
    # v6: mirror a clip left-to-right
    """
    ALTER TABLE items ADD COLUMN flip INTEGER NOT NULL DEFAULT 0;
    """,
    # v7: a clip is sent as a video or an animated GIF; output_note says what the prepared file turned out to be
    """
    ALTER TABLE items ADD COLUMN format TEXT NOT NULL DEFAULT 'video';
    ALTER TABLE items ADD COLUMN output_note TEXT;
    """,
    # v8: the user's codec (h264 | hevc) and picture size (long edge in px; NULL = as the source, up to 1080p)
    """
    ALTER TABLE items ADD COLUMN codec TEXT NOT NULL DEFAULT 'h264';
    ALTER TABLE items ADD COLUMN max_edge INTEGER;
    """,
    # v9: how a GIF loops: forward, or boomerang (forward then back)
    """
    ALTER TABLE items ADD COLUMN loop TEXT NOT NULL DEFAULT 'forward';
    """,
    # v10: a GIF's picture width (the ladder starts there); NULL = the feed width, 698 px
    """
    ALTER TABLE items ADD COLUMN gif_width INTEGER;
    """,
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, isolation_level=None, timeout=15)
        self.conn.row_factory = sqlite3.Row
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
            for f in (path, path + "-wal", path + "-shm"):  # the file holds imaglr keys: owner-only
                try:
                    if os.path.exists(f):
                        os.chmod(f, 0o600)
                except OSError:
                    pass
        self.conn.execute("PRAGMA busy_timeout=15000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    @classmethod
    def in_data_dir(cls, data_dir: str) -> Database:
        return cls(os.path.join(data_dir, DB_NAME))

    def migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= len(MIGRATIONS):
            return
        # Table rebuilds must not cascade deletes; this pragma only works outside a transaction.
        self.conn.execute("PRAGMA foreign_keys=OFF")
        try:
            for i in range(version, len(MIGRATIONS)):
                self.conn.executescript(f"BEGIN IMMEDIATE;{MIGRATIONS[i]}PRAGMA user_version = {i + 1}; COMMIT;")
        finally:
            self.conn.execute("PRAGMA foreign_keys=ON")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def fetchone(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    def fetchall(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def kv_get(self, key: str, default: str | None = None) -> str | None:
        row = self.fetchone("SELECT value FROM kv WHERE key=?", (key,))
        return row["value"] if row else default

    def kv_set(self, key: str, value: str | None) -> None:
        if value is None:
            self.execute("DELETE FROM kv WHERE key=?", (key,))
        else:
            self.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

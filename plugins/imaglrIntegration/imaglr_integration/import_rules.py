# SPDX-License-Identifier: AGPL-3.0-only
"""Import rules: what an imaglr tag becomes in Stash when a post is saved, remembered from the save review.

The mirror of the publishing tag rules. A rule maps one imaglr tag to Stash tags, performers and a studio, or to
nothing (always ignore it). Rules live in the plugin's database, never as Stash aliases: Stash's Auto Tag matches
file names against aliases, so imaglr's words would start tagging the library by file name.

Without a rule, an imaglr tag becomes the Stash tags, performers and studio whose name or alias equals it, ignoring
case; the review also suggests the Stash tag of any publishing rule that sends that imaglr tag. The plugin's own
queue and sent tags never come out of either.
"""

from __future__ import annotations

import json
from typing import Any

from .db import Database, now_iso

KINDS = ("tag", "performer", "studio")
SOURCES = ("rule", "match", "suggested", "none")  # why a row has the targets it has


def _key(tag: str) -> str:
    return " ".join(tag.split()).casefold()


def clean_targets(raw: Any) -> list[dict[str, Any]]:
    """Targets as the review sends them: existing Stash objects ({kind, id, name}) or a new tag to create
    ({kind: tag, create: true, name}). Anything else is dropped; duplicates too."""
    out: list[dict[str, Any]] = []
    seen = set()
    for t in raw if isinstance(raw, list) else []:
        if not isinstance(t, dict) or t.get("kind") not in KINDS:
            continue
        name = " ".join(str(t.get("name") or "").split())[:200]
        if t.get("create"):
            if t["kind"] != "tag" or not name or ("new", name.casefold()) in seen:
                continue
            seen.add(("new", name.casefold()))
            out.append({"kind": "tag", "create": True, "name": name})
            continue
        ident = str(t.get("id") or "")
        if not ident.isdigit() or (t["kind"], ident) in seen:
            continue
        seen.add((t["kind"], ident))
        out.append({"kind": t["kind"], "id": ident, "name": name})
    return out


def list_rules(db: Database) -> list[dict[str, Any]]:
    rows = db.fetchall("SELECT imaglr_tag, targets FROM import_rules ORDER BY imaglr_tag COLLATE NOCASE")
    return [{"imaglr_tag": r["imaglr_tag"], "targets": json.loads(r["targets"])} for r in rows]


def rules_for(db: Database, tags: list[str]) -> dict[str, list[dict[str, Any]]]:
    """The rules for these imaglr tags, by tag (case-folded)."""
    wanted = {_key(t) for t in tags}
    return {_key(r["imaglr_tag"]): r["targets"] for r in list_rules(db) if _key(r["imaglr_tag"]) in wanted}


def set_rule(db: Database, imaglr_tag: str, targets: list[dict[str, Any]]) -> None:
    """Remember what this imaglr tag becomes; [] means always ignore it. Only existing Stash objects are kept."""
    tag = " ".join(imaglr_tag.split())
    if not tag:
        return
    kept = [{"kind": t["kind"], "id": t["id"], "name": t.get("name") or ""} for t in clean_targets(targets) if not t.get("create")]
    ts = now_iso()
    db.execute("INSERT INTO import_rules(imaglr_tag, targets, created_at, updated_at) VALUES(?, ?, ?, ?) "
               "ON CONFLICT(imaglr_tag) DO UPDATE SET targets=excluded.targets, updated_at=excluded.updated_at",
               (tag, json.dumps(kept), ts, ts))


def delete_rule(db: Database, imaglr_tag: str) -> None:
    db.execute("DELETE FROM import_rules WHERE imaglr_tag=?", (imaglr_tag,))


def _matching(tag: str, candidates: list[dict[str, Any]], kind: str, exclude: set[str]) -> list[dict[str, Any]]:
    key = _key(tag)
    out = []
    for c in candidates:
        names = {_key(n) for n in [c.get("name") or ""] + list(c.get("aliases") or []) if n}
        if key in names and not names & exclude:
            out.append({"kind": kind, "id": str(c["id"]), "name": c.get("name") or ""})
    return out


def plan(imaglr_tags: list[str], rules: dict[str, list[dict[str, Any]]], candidates: dict[str, list[dict[str, Any]]],
         suggestions: dict[str, list[dict[str, Any]]], exclude: set[str]) -> list[dict[str, Any]]:
    """One row per imaglr tag: what it becomes in Stash and why. A rule wins; then exact name or alias matches;
    then a publishing rule's Stash tag as a suggestion; otherwise nothing (ignored)."""
    rows = []
    seen = set()
    for tag in imaglr_tags:
        key = _key(tag)
        if not key or key in seen:
            continue
        seen.add(key)
        if key in exclude:
            continue  # the plugin's own workflow tags: never shown, never applied
        if key in rules:
            rows.append({"tag": tag, "targets": rules[key], "source": "rule"})
            continue
        found = [t for kind in KINDS for t in _matching(tag, candidates.get(kind, []), kind, exclude)]
        if found:
            rows.append({"tag": tag, "targets": found, "source": "match"})
        elif suggestions.get(key):
            rows.append({"tag": tag, "targets": suggestions[key], "source": "suggested"})
        else:
            rows.append({"tag": tag, "targets": [], "source": "none"})
    return rows


def resolve(targets: list[dict[str, Any]]) -> dict[str, Any]:
    """What a set of targets means for a Stash scene or image: tag and performer ids, and one studio (the first;
    Stash has one studio per item)."""
    tag_ids, performer_ids, studio = [], [], None
    for t in targets:
        ident = t.get("id")
        if not ident:
            continue
        if t["kind"] == "tag" and ident not in tag_ids:
            tag_ids.append(ident)
        elif t["kind"] == "performer" and ident not in performer_ids:
            performer_ids.append(ident)
        elif t["kind"] == "studio" and studio is None:
            studio = ident
    return {"tag_ids": tag_ids, "performer_ids": performer_ids, "studio_id": studio}

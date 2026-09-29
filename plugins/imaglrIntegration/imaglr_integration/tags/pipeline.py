# SPDX-License-Identifier: AGPL-3.0-only
"""Tag suggestion pipeline (reference spec §8). Pure functions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..stash.models import Image, Marker, Scene

# Sources: "marker", "scene", "performer", "studio", "image", "gallery", "manual".

MAX_TAGS = 30
MAX_TAG_LEN = 64
DEFAULT_EXCLUDE = "^AI_"  # AI-tagger housekeeping tags


def parse_patterns(raw: str) -> tuple[re.Pattern[str], ...]:
    """Comma-separated, case-insensitive regexes. Invalid ones are skipped."""
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                out.append(re.compile(part, re.IGNORECASE))
            except re.error:
                continue
    return tuple(out)


@dataclass(frozen=True)
class RawTag:
    name: str
    source: str


@dataclass(frozen=True)
class SuggestedTag:
    tag: str
    source: str
    original: str
    reason: str | None = None  # 'too_long' | 'over_limit'

    def to_dict(self) -> dict:
        return {"tag": self.tag, "source": self.source, "original": self.original, "reason": self.reason}


@dataclass
class Suggestions:
    active: list[SuggestedTag] = field(default_factory=list)
    greyed: list[SuggestedTag] = field(default_factory=list)

    def active_names(self) -> list[str]:
        return [t.tag for t in self.active]

    def to_dict(self) -> dict:
        return {"active": [t.to_dict() for t in self.active], "greyed": [t.to_dict() for t in self.greyed]}


@dataclass(frozen=True)
class TagConfig:
    queue_tag: str
    done_tag: str
    exclude_patterns: tuple[re.Pattern[str], ...] = parse_patterns(DEFAULT_EXCLUDE)
    lowercase: bool = True
    max_tags: int = MAX_TAGS
    max_len: int = MAX_TAG_LEN


def collect_clip_sources(marker: Marker | None, scene: Scene | None) -> list[RawTag]:
    """Marker primary tag, marker tags, scene tags, performers, studio."""
    raw: list[RawTag] = []
    if marker:
        if marker.primary_tag:
            raw.append(RawTag(marker.primary_tag.name, "marker"))
        raw.extend(RawTag(t.name, "marker") for t in marker.tags)
    if scene:
        raw.extend(RawTag(t.name, "scene") for t in scene.tags)
        raw.extend(RawTag(p, "performer") for p in scene.performers)
        if scene.studio:
            raw.append(RawTag(scene.studio, "studio"))
    return raw


def collect_image_sources(image: Image) -> list[RawTag]:
    """Image tags, performers, studio, then the tags of each gallery the image is in."""
    raw: list[RawTag] = [RawTag(t.name, "image") for t in image.tags]
    raw.extend(RawTag(p, "performer") for p in image.performers)
    if image.studio:
        raw.append(RawTag(image.studio, "studio"))
    for g in image.galleries:
        raw.extend(RawTag(t.name, "gallery") for t in g.tags)
    return raw


def normalise(name: str, lowercase: bool) -> str:
    s = re.sub(r"\s+", " ", name.strip())
    return s.lower() if lowercase else s


def _mapped(name: str, mapping: dict) -> list[str]:
    """A Stash tag after the tag rules: itself, the rule's imaglr tags, or nothing (never suggest)."""
    if name.lower() not in mapping:
        return [name]
    value = mapping[name.lower()]
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def suggest(raw: list[RawTag], cfg: TagConfig, mapping: dict[str, list[str]]) -> Suggestions:
    """mapping keys are lower-cased Stash tag names; each value is the list of imaglr tags to send
    instead ([] means never suggest). A plain string or None is accepted as a one-tag list or []."""
    workflow = {cfg.queue_tag.lower(), cfg.done_tag.lower()}
    out = Suggestions()
    seen: set[str] = set()
    for r in raw:
        name = r.name.strip()
        if not name:
            continue
        # 1. workflow tags and excluded patterns
        if name.lower() in workflow:
            continue
        if any(p.search(name) for p in cfg.exclude_patterns):
            continue
        # 2. tag rules: one Stash tag may become several imaglr tags, or none
        for mapped in _mapped(name, mapping):
            # 3. normalise
            norm = normalise(mapped, cfg.lowercase)
            if not norm:
                continue
            # 4. too long
            if len(norm) > cfg.max_len:
                if norm.lower() not in seen:
                    seen.add(norm.lower())
                    out.greyed.append(SuggestedTag(norm, r.source, r.name, "too_long"))
                continue
            # 5. dedupe
            if norm.lower() in seen:
                continue
            seen.add(norm.lower())
            # 6. cap
            if len(out.active) < cfg.max_tags:
                out.active.append(SuggestedTag(norm, r.source, r.name))
            else:
                out.greyed.append(SuggestedTag(norm, r.source, r.name, "over_limit"))
    return out


def merge_suggestions(members: list[Suggestions], max_tags: int = MAX_TAGS) -> Suggestions:
    """Suggestions for a set: the members' suggestions in member order, deduplicated case-insensitively,
    with active tags past the cap moved to the front of the greyed list."""
    out = Suggestions()
    seen: set[str] = set()
    for sugg in members:
        for bucket, dest in ((sugg.active, out.active), (sugg.greyed, out.greyed)):
            for t in bucket:
                if t.tag.lower() not in seen:
                    seen.add(t.tag.lower())
                    dest.append(t)
    if len(out.active) > max_tags:
        overflow = out.active[max_tags:]
        out.active = out.active[:max_tags]
        out.greyed = [SuggestedTag(t.tag, t.source, t.original, "over_limit") for t in overflow] + out.greyed
    return out


def validate_tags(tags: list[str], cfg: TagConfig) -> list[str]:
    """Server-side check for user-edited tag lists. Returns the normalised list or raises ValueError."""
    out: list[str] = []
    seen: set[str] = set()
    for t in tags:
        norm = normalise(str(t), cfg.lowercase)
        if not norm:
            continue
        if len(norm) > cfg.max_len:
            raise ValueError(f"tag over {cfg.max_len} characters: {norm[:20]}…")
        if norm.lower() in seen:
            continue
        seen.add(norm.lower())
        out.append(norm)
    if len(out) > cfg.max_tags:
        raise ValueError(f"more than {cfg.max_tags} tags")
    return out


def dropped_tags(sent: list[str], returned: list[str]) -> list[str]:
    """Tags imaglr silently dropped (banned), compared case-insensitively."""
    got = {r.lower() for r in returned}
    return [t for t in sent if t.lower() not in got]

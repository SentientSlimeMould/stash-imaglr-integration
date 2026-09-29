# SPDX-License-Identifier: AGPL-3.0-only
"""Tolerant dataclass views over Stash GraphQL results. Unknown fields are ignored, missing ones default."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Formats Stash may store as a VideoFile that are still images for us: sent as-is, previewed with <img>.
ANIMATED_IMAGE_FORMATS = {"gif", "webp", "apng", "png", "avif", "heic", "heif", "jpg", "jpeg"}
# Stash reports ffmpeg-written JPEGs as "mjpeg" (docs/stash-plugin-facts.md §10a).
_FORMAT_ALIASES = {"mjpeg": "jpeg", "jpg": "jpeg"}


def _names(xs: list[dict] | None) -> list[str]:
    return [x["name"] for x in (xs or []) if x and x.get("name")]


def _float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _tags(xs: list[dict] | None) -> list[Tag]:
    return [t for t in (Tag.parse(x) for x in (xs or [])) if t]


def _ext(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


@dataclass
class Tag:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, d: dict | None) -> Tag | None:
        if not d or d.get("id") is None:
            return None
        return cls(str(d["id"]), d.get("name") or "", [a for a in (d.get("aliases") or []) if a])


@dataclass
class SceneFile:
    path: str
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    format: str | None = None
    size: int | None = None

    @classmethod
    def parse(cls, d: dict) -> SceneFile:
        return cls(
            path=d.get("path") or "",
            duration=_float(d.get("duration")),
            width=_int(d.get("width")),
            height=_int(d.get("height")),
            frame_rate=_float(d.get("frame_rate")),
            video_codec=d.get("video_codec"),
            audio_codec=d.get("audio_codec"),
            format=d.get("format"),
            size=_int(d.get("size")),
        )


@dataclass
class Scene:
    id: str
    title: str
    files: list[SceneFile] = field(default_factory=list)
    stream_url: str | None = None
    screenshot_url: str | None = None
    tags: list[Tag] = field(default_factory=list)
    performers: list[str] = field(default_factory=list)
    studio: str | None = None
    date: str | None = None
    created_at: str | None = None

    @property
    def primary_file(self) -> SceneFile | None:
        return self.files[0] if self.files else None

    @property
    def duration(self) -> float | None:
        f = self.primary_file
        return f.duration if f else None

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        f = self.primary_file
        if f and f.path:
            return f.path.replace("\\", "/").rsplit("/", 1)[-1]
        return f"Scene {self.id}"

    @classmethod
    def parse(cls, d: dict) -> Scene:
        paths = d.get("paths") or {}
        return cls(
            id=str(d["id"]),
            title=d.get("title") or "",
            files=[SceneFile.parse(f) for f in (d.get("files") or []) if f],
            stream_url=paths.get("stream"),
            screenshot_url=paths.get("screenshot"),
            tags=_tags(d.get("tags")),
            performers=_names(d.get("performers")),
            studio=(d.get("studio") or {}).get("name"),
            date=d.get("date"),
            created_at=d.get("created_at"),
        )


@dataclass
class Marker:
    id: str
    title: str
    seconds: float
    end_seconds: float | None
    primary_tag: Tag | None
    tags: list[Tag]
    screenshot_url: str | None
    preview_url: str | None
    scene: Scene | None
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def all_tag_ids(self) -> set[str]:
        ids = {t.id for t in self.tags}
        if self.primary_tag:
            ids.add(self.primary_tag.id)
        return ids

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.primary_tag and self.primary_tag.name:
            return self.primary_tag.name
        return f"Marker {self.id}"

    @classmethod
    def parse(cls, d: dict) -> Marker:
        return cls(
            id=str(d["id"]),
            title=d.get("title") or "",
            seconds=_float(d.get("seconds")) or 0.0,
            end_seconds=_float(d.get("end_seconds")),
            primary_tag=Tag.parse(d.get("primary_tag")),
            tags=_tags(d.get("tags")),
            screenshot_url=d.get("screenshot"),
            preview_url=d.get("preview"),
            scene=Scene.parse(d["scene"]) if d.get("scene") else None,
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )


@dataclass
class VisualFile:
    typename: str
    path: str
    width: int | None
    height: int | None
    size: int | None
    duration: float | None = None
    frame_rate: float | None = None
    video_codec: str | None = None
    format: str | None = None
    zip_path: str | None = None  # the containing zip, when the file is a zip member

    @property
    def is_video(self) -> bool:
        """True for real video containers only. Stash stores animated GIFs as VideoFile ("image clips")
        but they are still images for our purposes: sent as-is, previewed with <img>."""
        if self.typename != "VideoFile":
            return False
        fmt = (self.format or "").lower()
        return fmt not in ANIMATED_IMAGE_FORMATS and _ext(self.path) not in ANIMATED_IMAGE_FORMATS

    @property
    def is_animated(self) -> bool:
        """A VideoFile that is really an animated image (GIF). Animated WebP is an ImageFile and
        can't be told apart from a still one here."""
        return self.typename == "VideoFile" and not self.is_video

    @property
    def image_format(self) -> str:
        """Lower-case format with JPEG spellings unified ("mjpeg", "jpg" -> "jpeg"); falls back to the extension."""
        fmt = (self.format or "").lower() or _ext(self.path)
        return _FORMAT_ALIASES.get(fmt, fmt)

    @classmethod
    def parse(cls, d: dict) -> VisualFile:
        return cls(
            typename=d.get("__typename") or "ImageFile",
            path=d.get("path") or "",
            width=_int(d.get("width")),
            height=_int(d.get("height")),
            size=_int(d.get("size")),
            duration=_float(d.get("duration")),
            frame_rate=_float(d.get("frame_rate")),
            video_codec=d.get("video_codec"),
            format=d.get("format"),
            zip_path=(d.get("zip_file") or {}).get("path"),
        )


@dataclass
class Gallery:
    id: str
    title: str
    tags: list[Tag]


@dataclass
class Image:
    id: str
    title: str
    thumbnail_url: str | None
    image_url: str | None
    files: list[VisualFile]
    tags: list[Tag]
    performers: list[str]
    studio: str | None
    galleries: list[Gallery]
    date: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def primary_file(self) -> VisualFile | None:
        """The first visual file, as Stash uses. Byte-identical files give one image several entries."""
        return self.files[0] if self.files else None

    @property
    def is_video(self) -> bool:
        f = self.primary_file
        return bool(f and f.is_video)

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        f = self.primary_file
        if f and f.path:
            return f.path.replace("\\", "/").rsplit("/", 1)[-1]
        return f"Image {self.id}"

    @classmethod
    def parse(cls, d: dict) -> Image:
        paths = d.get("paths") or {}
        return cls(
            id=str(d["id"]),
            title=d.get("title") or "",
            thumbnail_url=paths.get("thumbnail"),
            image_url=paths.get("image"),
            files=[VisualFile.parse(f) for f in (d.get("visual_files") or []) if f],
            tags=_tags(d.get("tags")),
            performers=_names(d.get("performers")),
            studio=(d.get("studio") or {}).get("name"),
            galleries=[
                Gallery(str(g["id"]), g.get("title") or "", _tags(g.get("tags")))
                for g in (d.get("galleries") or [])
                if g and g.get("id") is not None
            ],
            date=d.get("date"),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )

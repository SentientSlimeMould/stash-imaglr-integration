# SPDX-License-Identifier: AGPL-3.0-only
"""Image processing decision tree (reference spec §7 Images). Pure functions."""

from __future__ import annotations

from dataclasses import dataclass, field

from .image_inspect import ImageInfo

ACCEPTED = {"JPEG", "PNG", "GIF", "WEBP"}
MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp", "MP4": "video/mp4"}
EXT = {"JPEG": "jpg", "PNG": "png", "GIF": "gif", "WEBP": "webp", "MP4": "mp4"}
STEP_DOWN_EDGES = (6000, 4096, 3072, 2048)


@dataclass
class ImagePlan:
    action: str  # 'strip' | 'reencode' | 'convert' | 'to_video'
    out_format: str  # 'JPEG' | 'PNG' | 'GIF' | 'WEBP' | 'MP4'
    steps: list = field(default_factory=list)
    quality: int = 92

    @property
    def mime(self) -> str:
        return MIME[self.out_format]

    @property
    def ext(self) -> str:
        return EXT[self.out_format]

    def to_dict(self) -> dict:
        return {"action": self.action, "out_format": self.out_format, "steps": self.steps}


def plan_image(info: ImageInfo, crop_aspect: str | None, limit_bytes: int,
               crop_edges: dict[str, float] | None = None) -> ImagePlan:
    trimming = bool(crop_edges) and any(float(v) > 0 for v in crop_edges.values())  # type: ignore[union-attr]
    cropping = bool(crop_aspect and crop_aspect != "original") or trimming
    needs_rotate = info.orientation not in (1, 0)
    over = info.bytes > limit_bytes

    if info.is_animated and info.format in ("GIF", "WEBP"):
        if cropping or over:
            reason = "crop" if cropping else "over size limit"
            return ImagePlan("to_video", "MP4", [f"animated {info.format} → MP4 ({reason})", "strip metadata"])
        return ImagePlan("strip", info.format, ["keep animation", "strip metadata"])

    if info.format in ACCEPTED and not needs_rotate and not cropping and not over:
        return ImagePlan("strip", info.format, ["strip metadata (lossless)"])

    steps: list[str] = []
    if needs_rotate:
        steps.append(f"rotate (EXIF orientation {info.orientation})")
    if trimming:
        steps.append("trim edges")
    if crop_aspect and crop_aspect != "original":
        steps.append(f"crop {crop_aspect}")

    if info.format in ACCEPTED:
        out = info.format
        if out == "GIF":  # still GIF that needs re-encode
            out = "PNG" if info.has_alpha else "JPEG"
            steps.append(f"convert GIF → {out}")
        steps.append(f"re-encode {out}" + (" q=92" if out in ("JPEG", "WEBP") else ""))
        steps.append("strip metadata")
        if over:
            steps.append("reduce size to fit limit")
        return ImagePlan("reencode", out, steps)

    out = "PNG" if info.has_alpha else "JPEG"
    steps.append(f"convert {info.format} → {out}")
    steps.append("strip metadata")
    if over:
        steps.append("reduce size to fit limit")
    return ImagePlan("convert", out, steps)


def step_down(out_format: str, alpha: bool, long_edge: int, size_bytes: int, limit_bytes: int) -> tuple | None:
    """Next size-guard action: None (fits), ('convert','JPEG'), ('resize', edge) or ('fail',)."""
    if size_bytes <= limit_bytes:
        return None
    if out_format == "PNG" and not alpha:
        return ("convert", "JPEG")
    for edge in STEP_DOWN_EDGES:
        if edge < long_edge:
            return ("resize", edge)
    return ("fail",)

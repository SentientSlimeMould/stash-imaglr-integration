# SPDX-License-Identifier: AGPL-3.0-only
"""Executes an ImagePlan: lossless metadata strip, or an ffmpeg re-encode with the size guard.

Re-encodes switch off ffmpeg's EXIF autorotation (ffmpeg 8 rotates JPEGs on decode) and apply the
orientation from our own header parse instead, so it is applied exactly once whatever the ffmpeg
version. Formats we cannot parse (AVIF, HEIC, TIFF, BMP...) are first decoded to an upright PNG with
ffmpeg's own orientation handling, then treated like any PNG. Every output is metadata-stripped after
encoding, which also removes the encoder's own comment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .. import log
from . import metadata_strip
from .ffmpeg_cmd import build_image_cmd, compute_crop
from .ffmpeg_run import encoders, finalise_part, run_ffmpeg
from .image_inspect import PARSED, ImageInfo, inspect_image
from .image_plan import EXT, MIME, ImagePlan, step_down

IMAGE_TIMEOUT = 600


class ImageTooLarge(Exception):
    pass


@dataclass
class ImageResult:
    path: str
    bytes: int
    mime: str
    width: int
    height: int


def _remove(path: str | None) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def _fit(width: int, height: int, edge: int) -> tuple[int, int]:
    f = edge / max(width, height)
    return max(1, int(width * f)), max(1, int(height * f))


def reencode(
    src: str,
    out_dir: str,
    base_name: str,
    plan: ImagePlan,
    info: ImageInfo,
    crop_aspect: str,
    crop_position: float,
    limit_bytes: int,
    *,
    ffmpeg: str,
    should_cancel=None,
    crop_edges: dict[str, float] | None = None,
) -> ImageResult:
    os.makedirs(out_dir, exist_ok=True)
    norm = part = None
    try:
        if info.format not in PARSED:
            norm = os.path.join(out_dir, f".{base_name}.source.png")
            cmd = build_image_cmd(ffmpeg, src, norm, "PNG", autorotate=True)
            run_ffmpeg(cmd, output=norm, should_cancel=should_cancel, timeout=IMAGE_TIMEOUT)
            src, info = norm, inspect_image(norm)
        elif info.orientation != 1:
            # Give ffmpeg a copy with no EXIF (so no orientation flag) and apply the rotation ourselves:
            # whether ffmpeg honours -noautorotate for images differs between versions (8.0 yes, 8.1 no).
            norm = os.path.join(out_dir, f".{base_name}.source{os.path.splitext(src)[1] or '.bin'}")
            metadata_strip.strip_file(src, norm)
            src = norm
        width, height = info.display_size
        crop = compute_crop(width, height, crop_aspect or "original", crop_position, crop_edges)
        if crop:
            width, height = crop.w, crop.h
        fmt = plan.out_format
        if fmt == "GIF":  # a still GIF that could not be stripped
            fmt = "PNG" if info.has_alpha else "JPEG"
        if fmt == "WEBP" and "libwebp" not in encoders(ffmpeg):
            fmt = "PNG" if info.has_alpha else "JPEG"
            log.warning(f"this ffmpeg has no WebP encoder; saving as {fmt}")
        size = None
        while True:
            part = os.path.join(out_dir, f"{base_name}.{EXT[fmt]}.part")
            cmd = build_image_cmd(
                ffmpeg, src, part, fmt, orientation=info.orientation, crop=crop, size=size, quality=plan.quality
            )
            run_ffmpeg(cmd, output=part, should_cancel=should_cancel, timeout=IMAGE_TIMEOUT)
            metadata_strip.strip_file(part, part)
            nbytes = os.path.getsize(part)
            out_w, out_h = size or (width, height)
            action = step_down(fmt, info.has_alpha, max(out_w, out_h), nbytes, limit_bytes)
            if action is None:
                break
            _remove(part)
            if action[0] == "convert":
                fmt = action[1]
                log.info(f"size guard: {nbytes} bytes, converting to {fmt}")
            elif action[0] == "resize":
                size = _fit(width, height, action[1])
                log.info(f"size guard: {nbytes} bytes, resizing long edge to {action[1]}")
            else:
                raise ImageTooLarge(f"image still {nbytes} bytes after every reduction")
        final = finalise_part(part)
        part = None
        return ImageResult(final, nbytes, MIME[fmt], out_w, out_h)
    finally:
        _remove(norm)
        _remove(part)


def process_image(
    src: str,
    out_dir: str,
    base_name: str,
    plan: ImagePlan,
    info: ImageInfo,
    crop_aspect: str,
    crop_position: float,
    limit_bytes: int,
    *,
    ffmpeg: str,
    should_cancel=None,
    crop_edges: dict[str, float] | None = None,
) -> ImageResult:
    """Handles 'strip', 'reencode' and 'convert'. For 'to_video' use video_export.gif_to_mp4."""
    if plan.action == "to_video":
        raise ValueError("animated images are converted with video_export.gif_to_mp4")
    os.makedirs(out_dir, exist_ok=True)
    if plan.action == "strip":
        out = os.path.join(out_dir, f"{base_name}.{plan.ext}")
        try:
            metadata_strip.strip_file(src, out)
        except metadata_strip.StripError as e:
            if info.is_animated:
                raise
            log.warning(f"lossless strip failed ({e}); re-encoding instead")
        else:
            size = os.path.getsize(out)
            if size <= limit_bytes:
                w, h = info.display_size
                return ImageResult(out, size, plan.mime, w, h)
            _remove(out)
            if info.is_animated:
                raise ImageTooLarge("animated image over limit after strip")
        plan = ImagePlan("reencode", plan.out_format)
    args = (src, out_dir, base_name, plan, info, crop_aspect, crop_position, limit_bytes)
    return reencode(*args, ffmpeg=ffmpeg, should_cancel=should_cancel, crop_edges=crop_edges)

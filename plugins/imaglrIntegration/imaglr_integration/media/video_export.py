# SPDX-License-Identifier: AGPL-3.0-only
"""Clip export orchestration: probe -> encode -> size guard -> thumbnail. Also frame grabs and
animated GIF -> MP4.

Sources are a local file path, or an HTTP URL plus request headers (e.g. Stash's ApiKey) that the
caller resolves. Progress is reported as a fraction through progress_cb; should_cancel() is polled
while ffmpeg runs (see ffmpeg_run).
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass

from .. import log
from . import ffmpeg_cmd as fc
from .ffmpeg_run import FfmpegError, finalise_part, run_ffmpeg
from .naming import output_name
from .probe import ProbeInfo, is_hdr, probe


class UnsupportedMedia(Exception):
    """ffmpeg cannot decode this source (e.g. animated WebP on ffmpeg 8.0)."""


@dataclass
class VideoSettings:
    ffmpeg: str
    ffprobe: str
    preset: str = "medium"
    crf: int = 20
    max_long_edge: int = 1920
    max_video_mb: float = 500


@dataclass
class ExportResult:
    path: str
    bytes: int
    width: int
    height: int
    hdr: bool = False
    thumb: str | None = None


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _output_dims(w: int, h: int, aspect: str, position: float, max_long_edge: int) -> tuple[int, int]:
    crop = fc.compute_crop(w, h, aspect, position)
    if crop:
        w, h = crop.w, crop.h
    scale = fc.compute_scale(w, h, max_long_edge)
    return scale if scale else (w, h)


def export_clip(
    src: str,
    out_dir: str,
    *,
    title: str,
    in_s: float,
    out_s: float,
    settings: VideoSettings,
    headers: dict[str, str] | None = None,
    aspect: str = "original",
    position: float = 0.5,
    mute: bool = False,
    progress_cb=None,
    should_cancel=None,
    bitrate_scale: float | None = None,
    probe_info: ProbeInfo | None = None,
) -> ExportResult:
    """Cut [in_s, out_s] of src to an MP4 in out_dir. bitrate_scale forces the two-pass encode at that
    fraction of the target bitrate (used to retry after imaglr rejects a file as too large)."""
    os.makedirs(out_dir, exist_ok=True)
    info = probe_info or probe(settings.ffprobe, src, headers)
    w, h = info.display_size
    if not w or not h:
        raise UnsupportedMedia("ffprobe could not read the video's dimensions")
    hdr = is_hdr(info)
    if hdr:
        log.warning("source is HDR; output will be 8-bit yuv420p without tone mapping")
    duration = max(0.1, out_s - in_s)
    final = os.path.join(out_dir, output_name(title, in_s, out_s))
    part = final + ".part"
    for stale in glob.glob(os.path.join(glob.escape(out_dir), "*.part")):
        _remove(stale)

    common = dict(
        ffmpeg=settings.ffmpeg,
        src=src,
        out=part,
        in_s=in_s,
        out_s=out_s,
        width=w,
        height=h,
        fps=info.fps,
        aspect=aspect,
        position=position,
        mute=mute,
        has_audio=info.has_audio,
        preset=settings.preset,
        crf=settings.crf,
        max_long_edge=settings.max_long_edge,
        headers=headers,
    )
    run = dict(output=part, duration_s=duration, progress_cb=progress_cb, should_cancel=should_cancel)
    limit_bytes = int(settings.max_video_mb * 1024 * 1024 * 0.95)

    if bitrate_scale is None:
        run_ffmpeg(fc.build_clip_cmd(**common), progress_range=(0.0, 0.95), **run)
        size = os.path.getsize(part)
        if size > limit_bytes:
            log.info(f"output {size} bytes exceeds the limit; re-encoding two-pass")
            _remove(part)
            bitrate_scale = 1.0
    if bitrate_scale is not None:
        audio_kbps = 0 if (mute or not info.has_audio) else fc.AUDIO_KBPS
        kbps = fc.target_kbps(settings.max_video_mb, duration, audio_kbps, bitrate_scale)
        passlog = os.path.join(out_dir, "x264pass")
        first, second = fc.build_two_pass_cmds(kbps, passlog, **common)
        try:
            run_ffmpeg(first, progress_range=(0.0, 0.45), **run)
            run_ffmpeg(second, progress_range=(0.45, 0.95), **run)
        finally:
            for f in glob.glob(glob.escape(passlog) + "*"):
                _remove(f)
    final_path = finalise_part(part)
    size = os.path.getsize(final_path)
    thumb: str | None = os.path.join(out_dir, "thumb.jpg")
    try:
        cmd = fc.build_thumb_cmd(settings.ffmpeg, final_path, thumb, min(1.0, duration / 2))
        run_ffmpeg(cmd, output=thumb, should_cancel=should_cancel, timeout=120)
    except FfmpegError as e:  # the thumbnail is best-effort
        log.warning(f"thumbnail failed: {e}")
        thumb = None
    if progress_cb:
        progress_cb(1.0)
    ow, oh = _output_dims(w, h, aspect, position, settings.max_long_edge)
    return ExportResult(final_path, size, ow, oh, hdr, thumb)


def grab_frame(
    src: str,
    t: float,
    out: str,
    ffmpeg: str,
    headers: dict[str, str] | None = None,
    should_cancel=None,
) -> str:
    """Write the frame at t seconds as a JPEG (it then goes through the image rules like any upload)."""
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    part = out + ".part"
    cmd = fc.build_frame_grab_cmd(ffmpeg, src, part, t, headers)
    run_ffmpeg(cmd, output=part, should_cancel=should_cancel, timeout=120)
    if os.path.getsize(part) == 0:
        _remove(part)
        raise FfmpegError("frame grab produced an empty file (is t past the end?)")
    return finalise_part(part)


def gif_to_mp4(
    src: str,
    out_dir: str,
    base_name: str,
    settings: VideoSettings,
    *,
    aspect: str = "original",
    position: float = 0.5,
    progress_cb=None,
    should_cancel=None,
) -> ExportResult:
    """Convert an animated GIF (or animated WebP, where ffmpeg can decode it) to a silent MP4."""
    os.makedirs(out_dir, exist_ok=True)
    info = probe(settings.ffprobe, src)
    if not info.width or not info.height:
        raise UnsupportedMedia(
            "this ffmpeg cannot decode the animation (ffmpeg 8.0 has no animated WebP decoder); "
            "send it uncropped and under the image size limit instead"
        )
    final = os.path.join(out_dir, f"{base_name}.mp4")
    part = final + ".part"
    cmd = fc.build_gif_to_mp4_cmd(
        settings.ffmpeg,
        src,
        part,
        width=info.width,
        height=info.height,
        fps=info.fps or 15,
        aspect=aspect,
        position=position,
        preset=settings.preset,
        crf=settings.crf,
        max_long_edge=settings.max_long_edge,
    )
    run_ffmpeg(cmd, output=part, duration_s=info.duration, progress_cb=progress_cb, should_cancel=should_cancel)
    path = finalise_part(part)
    ow, oh = _output_dims(info.width, info.height, aspect, position, settings.max_long_edge)
    return ExportResult(path, os.path.getsize(path), ow, oh)

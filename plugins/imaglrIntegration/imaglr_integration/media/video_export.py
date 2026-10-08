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
from .ffmpeg_run import FfmpegError, encoders, finalise_part, run_capture, run_ffmpeg
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
    max_video_mb: float = 100  # imaglr's API refuses a request over 100 MiB (measured 2026-10-08), whatever its docs say
    codec: str = "h264"  # or "hevc": the user's choice for the clip


def hevc_available(ffmpeg: str) -> bool:
    return "libx265" in encoders(ffmpeg)


@dataclass
class ExportResult:
    path: str
    bytes: int
    width: int
    height: int
    hdr: bool = False
    thumb: str | None = None
    note: str | None = None  # what the user gets, e.g. "GIF · 9.4 MB · 480 px · 10 fps"


class GifTooLarge(Exception):
    """Even the smallest rung of the ladder is over imaglr's limit; `fit_seconds` is about how long the clip
    could be at that rung and still fit."""

    def __init__(self, size: int, limit: int, fit_seconds: float):
        super().__init__(f"{size} bytes at the smallest setting; limit {limit}")
        self.size, self.limit, self.fit_seconds = size, limit, fit_seconds


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _output_dims(w: int, h: int, aspect: str, position: float, max_long_edge: int,
                 edges: dict[str, float] | None = None) -> tuple[int, int]:
    crop = fc.compute_crop(w, h, aspect, position, edges)
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
    flip: bool = False,
    progress_cb=None,
    should_cancel=None,
    bitrate_scale: float | None = None,
    probe_info: ProbeInfo | None = None,
    previous_bytes: int | None = None,
    edges: dict[str, float] | None = None,
    cover_t: float | None = None,
) -> ExportResult:
    """Cut [in_s, out_s] of src to an MP4 in out_dir with the codec and picture size in `settings`, under
    settings.max_video_mb. A clip that fits at the usual quality (CRF) is one encode; otherwise it is encoded
    two-pass at the bitrate that fits, and a clip that obviously can't fit skips the first encode. The result's
    `note` says what came out. bitrate_scale forces the two-pass encode at that fraction of the target bitrate
    (used to retry after imaglr rejects a file as too large); with previous_bytes, the target is also at most
    that fraction of the rejected file's size."""
    os.makedirs(out_dir, exist_ok=True)
    info = probe_info or probe(settings.ffprobe, src, headers)
    w, h = info.display_size
    if not w or not h:
        raise UnsupportedMedia("ffprobe could not read the video's dimensions")
    hdr = is_hdr(info)
    if hdr:
        log.warning("source is HDR; output will be 8-bit yuv420p without tone mapping")
    duration = max(0.1, out_s - in_s) + (fc.COVER_HOLD_SECONDS if cover_t is not None else 0)  # what comes out
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
        flip=flip,
        has_audio=info.has_audio,
        preset=settings.preset,
        crf=settings.crf,
        max_long_edge=settings.max_long_edge,
        headers=headers,
        edges=edges,
        codec=settings.codec,
        cover_t=cover_t,
    )
    run = dict(output=part, duration_s=duration, progress_cb=progress_cb, should_cancel=should_cancel)
    limit_bytes = int(settings.max_video_mb * 1024 * 1024 * 0.95)
    ow, oh = _output_dims(w, h, aspect, position, settings.max_long_edge, edges)

    # The bitrate the limit allows for this length of clip. A clip that obviously can't fit at the usual
    # quality skips the first encode instead of wasting it to find out.
    audio_kbps = 0 if (mute or not info.has_audio) else fc.AUDIO_KBPS
    kbps = fc.target_kbps(settings.max_video_mb, duration, audio_kbps, bitrate_scale or 1.0)
    if previous_bytes:
        kbps = min(kbps, fc.kbps_for_size(previous_bytes, duration, audio_kbps, bitrate_scale or 1.0))
    hopeless = kbps < fc.typical_kbps(settings.codec, max(ow, oh)) * 0.7

    if bitrate_scale is None and not hopeless:
        run_ffmpeg(fc.build_clip_cmd(**common), progress_range=(0.0, 0.95), **run)
        size = os.path.getsize(part)
        if size > limit_bytes:
            log.info(f"output {size} bytes exceeds the limit; re-encoding two-pass")
            _remove(part)
            bitrate_scale = 1.0
    if bitrate_scale is not None or hopeless:
        if hopeless:
            log.info(f"{duration:.0f} s clip won't fit at the usual quality; encoding at {kbps} kbps")
        passlog = os.path.join(out_dir, "passlog")
        first, second = fc.build_two_pass_cmds(kbps, passlog, **common)
        try:
            run_ffmpeg(first, progress_range=(0.0, 0.45), **run)
            run_ffmpeg(second, progress_range=(0.45, 0.95), **run)
        finally:
            for f in glob.glob(glob.escape(passlog) + "*"):
                _remove(f)
    final_path = finalise_part(part)
    size = os.path.getsize(final_path)
    note = video_note(settings.codec, size, max(ow, oh), cover=cover_t is not None)
    thumb: str | None = os.path.join(out_dir, "thumb.jpg")
    try:  # the card's picture: the cover when there is one
        cmd = fc.build_thumb_cmd(settings.ffmpeg, final_path, thumb, 0.2 if cover_t is not None else min(1.0, duration / 2))
        run_ffmpeg(cmd, output=thumb, should_cancel=should_cancel, timeout=120)
    except FfmpegError as e:  # the thumbnail is best-effort
        log.warning(f"thumbnail failed: {e}")
        thumb = None
    if progress_cb:
        progress_cb(1.0)
    return ExportResult(final_path, size, ow, oh, hdr, thumb, note)


def video_note(codec: str, size: int, long_edge: int, cover: bool = False) -> str:
    """What the clip turned out to be, e.g. "H.265 · 92.1 MB · 1280 px · with cover"."""
    note = f"{fc.CODEC_LABELS.get(codec, codec)} · {size / 1048576:.1f} MB · {long_edge} px"
    return note + " · with cover" if cover else note


def gif_note(size: int, width: int, fps: int, loop: str = "forward", fmt: str = "gif") -> str:
    loop_part = " · boomerang" if loop == "boomerang" else ""
    label = "WebP" if fmt == "webp" else "GIF"
    return f"{label} · {size / 1048576:.1f} MB · {width} px wide · {fps} fps{loop_part}"


def webp_available(ffmpeg: str) -> bool:
    return "libwebp_anim" in encoders(ffmpeg)


def export_gif(src: str, out_dir: str, **kw) -> ExportResult:
    """Cut a clip to an animated GIF under the target; see export_animation."""
    return export_animation("gif", src, out_dir, **kw)


def export_webp(src: str, out_dir: str, **kw) -> ExportResult:
    """Cut a clip to an animated WebP under the target; see export_animation."""
    return export_animation("webp", src, out_dir, **kw)


def export_animation(
    fmt: str,
    src: str,
    out_dir: str,
    *,
    title: str,
    in_s: float,
    out_s: float,
    settings: VideoSettings,
    target_bytes: int,
    limit_bytes: int,
    headers: dict[str, str] | None = None,
    aspect: str = "original",
    position: float = 0.5,
    flip: bool = False,
    progress_cb=None,
    should_cancel=None,
    probe_info: ProbeInfo | None = None,
    edges: dict[str, float] | None = None,
    loop: str = "forward",
    max_width: int | None = None,
    fps: int | None = None,
) -> ExportResult:
    """Cut [in_s, out_s] of src to an animated GIF or WebP under target_bytes, going down the format's quality
    ladder until it fits (starting at max_width when given). The bottom rung is accepted up to limit_bytes
    (imaglr's ceiling); beyond that GifTooLarge says how much shorter the clip would have to be."""
    os.makedirs(out_dir, exist_ok=True)
    info = probe_info or probe(settings.ffprobe, src, headers)
    w, h = info.display_size
    if not w or not h:
        raise UnsupportedMedia("ffprobe could not read the video's dimensions")
    duration = max(0.1, out_s - in_s)
    final = os.path.join(out_dir, output_name(title, in_s, out_s, fmt))
    part = final + ".part"
    for stale in glob.glob(os.path.join(glob.escape(out_dir), "*.part")):
        _remove(stale)

    size = 0
    rungs = fc.WEBP_LADDER if fmt == "webp" else fc.GIF_LADDER
    if max_width:  # the user's picture size: the ladder starts at that rung
        rungs = tuple(r for r in rungs if r[0] <= max_width) or rungs[-1:]
    wanted_fps = fps
    for n, (rung_width, fps, quality) in enumerate(rungs):
        if wanted_fps:  # the user's frame rate, at every rung
            fps = wanted_fps
        long_edge = fc.gif_long_edge_cap(w, h, aspect, position, rung_width, edges)
        common = dict(aspect=aspect, position=position, flip=flip, headers=headers, edges=edges, loop=loop)
        if fmt == "webp":
            cmd = fc.build_webp_cmd(settings.ffmpeg, src, part, in_s, out_s, w, h, long_edge=long_edge, fps=fps,
                                    quality=quality, **common)
        else:
            cmd = fc.build_gif_cmd(settings.ffmpeg, src, part, in_s, out_s, w, h, long_edge=long_edge, gif_fps=fps,
                                   colors=quality, **common)
        lo, hi = 0.9 * n / len(rungs), 0.9 * (n + 1) / len(rungs)
        run_ffmpeg(cmd, output=part, duration_s=duration, progress_cb=progress_cb, should_cancel=should_cancel,
                   progress_range=(lo, hi))
        size = os.path.getsize(part)
        if size <= target_bytes:
            break
        if n < len(rungs) - 1:
            log.info(f"{fmt.upper()} is {size / 1048576:.1f} MB at {rung_width} px wide / {fps} fps; trying a smaller setting")
            _remove(part)
    else:
        rung_width, fps, quality = rungs[-1]
        fps = wanted_fps or fps
        long_edge = fc.gif_long_edge_cap(w, h, aspect, position, rung_width, edges)
        if size > limit_bytes:
            _remove(part)
            raise GifTooLarge(size, limit_bytes, fit_seconds=max(1.0, duration * limit_bytes * 0.9 / size))
    final_path = finalise_part(part)
    thumb: str | None = os.path.join(out_dir, "thumb.jpg")
    try:
        run_ffmpeg(fc.build_thumb_cmd(settings.ffmpeg, final_path, thumb, min(1.0, duration / 2)),
                   output=thumb, should_cancel=should_cancel, timeout=120)
    except FfmpegError as e:  # best-effort
        log.warning(f"thumbnail failed: {e}")
        thumb = None
    if progress_cb:
        progress_cb(1.0)
    ow, oh = _output_dims(w, h, aspect, position, long_edge, edges)
    return ExportResult(final_path, size, ow, oh, False, thumb, gif_note(size, ow, fps, loop, fmt))


def detect_edges(ffmpeg: str, src: str, width: int, height: int, times: list[float],
                 headers: dict[str, str] | None = None) -> dict[str, float]:
    """Edge trims that cut the black borders off a width×height picture, judged over a few frames at each of
    `times` (seconds). The widest picture seen wins, so a dark frame can't shrink the result. All zero when no
    border is found."""
    rect: fc.CropRect | None = None
    for t in times:
        _, err, code = run_capture(fc.build_cropdetect_cmd(ffmpeg, src, t, headers=headers), timeout=120)
        if code != 0:
            raise FfmpegError(f"ffmpeg exit {code}", code, err.decode(errors="replace")[-500:])
        found = fc.parse_cropdetect(err.decode(errors="replace"))
        if found is None:
            continue
        if rect is None:
            rect = found
        else:  # the union of the two rectangles
            x, y = min(rect.x, found.x), min(rect.y, found.y)
            rect = fc.CropRect(max(rect.x + rect.w, found.x + found.w) - x, max(rect.y + rect.h, found.y + found.h) - y, x, y)
    if rect is None:
        return fc.clean_edges(None)
    return fc.edges_from_rect(width, height, rect)


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
    edges: dict[str, float] | None = None,
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
        edges=edges,
        preset=settings.preset,
        crf=settings.crf,
        max_long_edge=settings.max_long_edge,
    )
    run_ffmpeg(cmd, output=part, duration_s=info.duration, progress_cb=progress_cb, should_cancel=should_cancel)
    path = finalise_part(part)
    ow, oh = _output_dims(info.width, info.height, aspect, position, settings.max_long_edge, edges)
    return ExportResult(path, os.path.getsize(path), ow, oh)

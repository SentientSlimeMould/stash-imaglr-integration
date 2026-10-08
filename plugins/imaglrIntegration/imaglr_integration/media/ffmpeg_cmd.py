# SPDX-License-Identifier: AGPL-3.0-only
"""Pure ffmpeg argument builders (reference spec §7). No subprocesses here.

Every builder takes the ffmpeg binary path first; the plugin resolves it from Stash's `systemStatus`.
Process priority (nice) is applied by ffmpeg_run, not here.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

ASPECTS: dict[str, float | None] = {"original": None, "9:16": 9 / 16, "4:5": 4 / 5, "1:1": 1.0}
AUDIO_KBPS = 128
MAX_FPS = 60.0
MIN_KBPS = 200

# The user chooses the codec and the picture size for each clip; the plugin only fits the file under the
# upload limit by bitrate. These are the bitrates (kbps) a CRF-20 encode of ordinary footage tends to come out
# at for each long edge, used to skip a first encode that would certainly be over the limit, and (mirrored in
# the editor, src/ui/lib/video.ts) to estimate sizes and warn when the budget is too thin for the picture.
VIDEO_CODECS = ("h264", "hevc")
CODEC_LABELS = {"h264": "H.264", "hevc": "H.265"}
PICTURE_SIZES = (1280, 854)  # the "720p" and "480p" choices, as long edges; None means as the source (up to 1080p)
TYPICAL_KBPS: dict[int, int] = {1920: 6000, 1280: 3000, 854: 1500, 640: 900}
HEVC_FACTOR = 0.6  # H.265 needs about this much of H.264's bitrate for the same look


def typical_kbps(codec: str, long_edge: int) -> int:
    """What a CRF-20 encode of this codec at this picture size tends to need."""
    rung = max((e for e in TYPICAL_KBPS if e <= long_edge), default=min(TYPICAL_KBPS))
    kbps = TYPICAL_KBPS[rung]
    return int(kbps * HEVC_FACTOR) if codec == "hevc" else kbps
# ffmpeg's mjpeg -q:v 2 with 4:2:0 chroma matches libjpeg quality 92 (4:2:0) on PSNR, measured on ffmpeg 8.
JPEG_QSCALE = 2


def even(n: int) -> int:
    n = int(n)
    return n if n % 2 == 0 else n - 1


@dataclass(frozen=True)
class CropRect:
    w: int
    h: int
    x: int
    y: int


# Edge trims: fractions (0..1) of the picture cut off each side, e.g. {"top": 0.1, "bottom": 0.1} for black bars.
EDGE_NAMES = ("top", "right", "bottom", "left")
MAX_EDGE = 0.45  # no single side may take more than this ...
MIN_KEPT = 0.1  # ... and at least this much of each dimension must remain


def clean_edges(raw: object) -> dict[str, float]:
    """Edge trims from the editor (or the database) as a complete, bounded dict; junk counts as no trim."""
    out = {}
    for name in EDGE_NAMES:
        try:
            v = float((raw or {}).get(name, 0)) if isinstance(raw, dict) else 0.0  # type: ignore[union-attr]
        except (TypeError, ValueError):
            v = 0.0
        out[name] = round(min(MAX_EDGE, max(0.0, v if v == v else 0.0)), 4)
    for a, b in (("left", "right"), ("top", "bottom")):
        over = out[a] + out[b] - (1 - MIN_KEPT)
        if over > 0:  # take the excess off both sides equally
            out[a], out[b] = max(0.0, out[a] - over / 2), max(0.0, out[b] - over / 2)
    return out


def has_edges(edges: dict[str, float] | None) -> bool:
    return bool(edges) and any(edges.get(n, 0) > 0 for n in EDGE_NAMES)  # type: ignore[union-attr]


def edge_rect(width: int, height: int, edges: dict[str, float] | None) -> CropRect | None:
    """The picture left after the edge trims, or None when nothing is trimmed."""
    if not has_edges(edges) or width <= 0 or height <= 0:
        return None
    e = clean_edges(edges)
    x = even(int(round(width * e["left"])))
    y = even(int(round(height * e["top"])))
    w = max(2, even(int(round(width * (1 - e["left"] - e["right"])))))
    h = max(2, even(int(round(height * (1 - e["top"] - e["bottom"])))))
    w, h = min(w, even(width) - x), min(h, even(height) - y)
    if x == 0 and y == 0 and w == even(width) and h == even(height):
        return None
    return CropRect(w, h, x, y)


def compute_crop(width: int, height: int, aspect: str, position: float,
                 edges: dict[str, float] | None = None) -> CropRect | None:
    """Edge trims first, then the aspect preset inside what is left; position 0..1 slides along the cropped
    axis. None when the whole picture is kept."""
    inset = edge_rect(width, height, edges)
    ox, oy = (inset.x, inset.y) if inset else (0, 0)
    if inset:
        width, height = inset.w, inset.h
    ratio = ASPECTS.get(aspect)
    if ratio is None or width <= 0 or height <= 0:
        return inset
    position = min(1.0, max(0.0, float(position)))
    src_ratio = width / height
    if abs(src_ratio - ratio) < 1e-6:
        return inset
    if src_ratio > ratio:
        cw = max(2, even(int(height * ratio)))
        ch = even(height)
        x = even(int(round((width - cw) * position)))
        y = 0
    else:
        cw = even(width)
        ch = max(2, even(int(width / ratio)))
        x = 0
        y = even(int(round((height - ch) * position)))
    if not inset and cw == even(width) and ch == even(height) and x == 0 and y == 0 and width % 2 == 0 and height % 2 == 0:
        return None
    return CropRect(cw, ch, ox + x, oy + y)


def build_cropdetect_cmd(ffmpeg: str, src: str, t: float, frames: int = 12,
                         headers: dict[str, str] | None = None) -> list[str]:
    """Let ffmpeg find the picture inside black borders over a few frames from t; the result is on stderr as
    `crop=w:h:x:y` lines (loglevel info). reset=0 keeps the widest picture seen across the frames."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "info", "-nostats"]
    cmd += _headers_arg(headers)
    cmd += ["-ss", f"{t:.3f}", "-i", src, "-frames:v", str(frames), "-an"]
    cmd += ["-vf", "cropdetect=limit=24:round=2:reset=0", "-f", "null", os.devnull]
    return cmd


_CROPDETECT = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def parse_cropdetect(stderr: str) -> CropRect | None:
    """The last crop rectangle cropdetect reported, or None when it found nothing."""
    found = _CROPDETECT.findall(stderr)
    if not found:
        return None
    w, h, x, y = (int(v) for v in found[-1])
    return CropRect(w, h, x, y) if w > 0 and h > 0 else None


def edges_from_rect(width: int, height: int, rect: CropRect) -> dict[str, float]:
    """Edge trims that reproduce `rect` on a width×height picture, bounded like any edit."""
    if width <= 0 or height <= 0:
        return clean_edges(None)
    raw = {"left": rect.x / width, "top": rect.y / height,
           "right": (width - rect.x - rect.w) / width, "bottom": (height - rect.y - rect.h) / height}
    return clean_edges({k: 0.0 if v < 0.005 else v for k, v in raw.items()})


def compute_scale(width: int, height: int, max_long_edge: int) -> tuple[int, int] | None:
    """Return (w, h) if a scale filter is needed: downscale to max long edge, never upscale, even dims."""
    long_edge = max(width, height)
    if long_edge > max_long_edge and max_long_edge > 0:
        f = max_long_edge / long_edge
        return max(2, even(int(width * f))), max(2, even(int(height * f)))
    if width % 2 or height % 2:
        return max(2, even(width)), max(2, even(height))
    return None


def build_filter_chain(width: int, height: int, aspect: str, position: float, max_long_edge: int, fps: float,
                       flip: bool = False, edges: dict[str, float] | None = None) -> str:
    parts: list[str] = []
    crop = compute_crop(width, height, aspect, position, edges)
    w, h = width, height
    if crop:
        parts.append(f"crop={crop.w}:{crop.h}:{crop.x}:{crop.y}")
        w, h = crop.w, crop.h
    scale = compute_scale(w, h, max_long_edge)
    if scale:
        parts.append(f"scale={scale[0]}:{scale[1]}:flags=lanczos")
    if fps and fps > MAX_FPS:
        parts.append(f"fps={int(MAX_FPS)}")
    if flip:
        parts.append("hflip")  # last: the crop was chosen on the unflipped picture
    return ",".join(parts)


# GIF quality ladder, best first: (width px, frames per second, palette colours). The export tries each rung
# until the file is under the target; a lower rung is roughly 60-70 % of the size of the one above. The top
# rung is imaglr's feed width (698 px), so a GIF is never shown upscaled there.
GIF_LADDER: tuple[tuple[int, int, int], ...] = (
    (698, 15, 256),
    (560, 12, 256),
    (480, 12, 128),
    (400, 10, 128),
    (320, 8, 64),
)
GIF_LOOPS = ("forward", "boomerang")
# Animated WebP ladder, best first: (width px, frames per second, libwebp quality 0-100). WebP keeps full colour
# and is usually a third to a half of a GIF's size, so the same clip fits with room to spare.
WEBP_LADDER: tuple[tuple[int, int, int], ...] = (
    (698, 15, 80),
    (560, 12, 75),
    (480, 12, 70),
    (400, 10, 65),
    (320, 8, 60),
)


def animation_filters(width: int, height: int, aspect: str, position: float, long_edge: int, fps: int,
                      flip: bool = False, edges: dict[str, float] | None = None, loop: str = "forward") -> str:
    """The frame chain a GIF or WebP starts from: frame-rate cap, crop, scale, flip, and for a boomerang the
    frames played forward then backward (without repeating the turning frame)."""
    chain = build_filter_chain(width, height, aspect, position, long_edge, 0, flip, edges)
    vf = f"fps={fps}" + ("," + chain if chain else "")
    if loop == "boomerang":
        vf += ",split[f][r];[r]reverse,trim=start_frame=1[rv];[f][rv]concat=n=2:v=1:a=0"
    return vf


def build_webp_cmd(
    ffmpeg: str,
    src: str,
    out: str,
    in_s: float,
    out_s: float,
    width: int,
    height: int,
    *,
    long_edge: int,
    fps: int,
    quality: int,
    aspect: str = "original",
    position: float = 0.5,
    flip: bool = False,
    headers: dict[str, str] | None = None,
    edges: dict[str, float] | None = None,
    loop: str = "forward",
) -> list[str]:
    """One-pass animated WebP (libwebp_anim), looping forever, no sound."""
    duration = max(0.1, out_s - in_s)
    vf = animation_filters(width, height, aspect, position, long_edge, fps, flip, edges, loop)
    cmd = _base(ffmpeg)
    cmd += _headers_arg(headers)
    cmd += ["-ss", f"{in_s:.3f}", "-t", f"{duration:.3f}", "-i", src, "-an", "-filter_complex", vf]
    cmd += ["-c:v", "libwebp_anim", "-q:v", str(quality), "-compression_level", "4", "-loop", "0", "-f", "webp", out]
    return cmd


def gif_long_edge_cap(width: int, height: int, aspect: str, position: float, rung_width: int,
                      edges: dict[str, float] | None = None) -> int:
    """The long-edge cap that makes the GIF `rung_width` wide after cropping: for a landscape picture that is
    the width itself; a portrait one is taller than it is wide."""
    crop = compute_crop(width, height, aspect, position, edges)
    w, h = (crop.w, crop.h) if crop else (width, height)
    if w <= 0 or h <= 0 or w >= h:
        return rung_width
    return int(round(rung_width * h / w))


def build_gif_cmd(
    ffmpeg: str,
    src: str,
    out: str,
    in_s: float,
    out_s: float,
    width: int,
    height: int,
    *,
    long_edge: int,
    gif_fps: int,
    colors: int,
    aspect: str = "original",
    position: float = 0.5,
    flip: bool = False,
    headers: dict[str, str] | None = None,
    edges: dict[str, float] | None = None,
    loop: str = "forward",
) -> list[str]:
    """One-pass animated GIF: frame-rate cap, crop, scale and flip, then a palette made from the clip itself
    (stats_mode=diff favours what moves) and ordered dithering with per-frame rectangles of change. A
    boomerang plays the frames forward then backward (without repeating the turning frame)."""
    duration = max(0.1, out_s - in_s)
    vf = animation_filters(width, height, aspect, position, long_edge, gif_fps, flip, edges, loop)
    vf += (f",split[a][b];[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
           f"[b][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle")
    cmd = _base(ffmpeg)
    cmd += _headers_arg(headers)
    # -t before -i cuts the source, not the output: a boomerang's output is twice as long as its source
    cmd += ["-ss", f"{in_s:.3f}", "-t", f"{duration:.3f}", "-i", src, "-an", "-filter_complex", vf, "-loop", "0", "-f", "gif", out]
    return cmd


def _headers_arg(headers: dict[str, str] | None) -> list[str]:
    if not headers:
        return []
    return ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]


def _base(ffmpeg: str, progress: bool = True) -> list[str]:
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-nostats", "-y"]
    if progress:
        cmd += ["-progress", "pipe:1"]
    return cmd


def build_clip_cmd(
    ffmpeg: str,
    src: str,
    out: str,
    in_s: float,
    out_s: float,
    width: int,
    height: int,
    fps: float,
    *,
    aspect: str = "original",
    position: float = 0.5,
    mute: bool = False,
    flip: bool = False,
    has_audio: bool = True,
    preset: str = "medium",
    crf: int = 20,
    max_long_edge: int = 1920,
    headers: dict[str, str] | None = None,
    two_pass: tuple[int, int] | None = None,  # (pass number, target kbps)
    passlog: str | None = None,
    codec: str = "h264",
    edges: dict[str, float] | None = None,
) -> list[str]:
    duration = max(0.1, out_s - in_s)
    cmd = _base(ffmpeg)
    cmd += _headers_arg(headers)
    cmd += ["-ss", f"{in_s:.3f}", "-i", src, "-t", f"{duration:.3f}", "-map", "0:v:0"]
    include_audio = has_audio and not mute
    if include_audio:
        cmd += ["-map", "0:a:0?"]
    vf = build_filter_chain(width, height, aspect, position, max_long_edge, fps, flip, edges)
    if vf:
        cmd += ["-vf", vf]
    if codec == "hevc":
        # hvc1 is the tag Safari and QuickTime need; x265's own log is silenced (ffmpeg's -loglevel doesn't reach it)
        cmd += ["-c:v", "libx265", "-tag:v", "hvc1", "-preset", preset, "-pix_fmt", "yuv420p",
                "-x265-params", "log-level=error"]
    else:
        cmd += ["-c:v", "libx264", "-profile:v", "high", "-preset", preset, "-pix_fmt", "yuv420p"]
    if two_pass:
        pass_no, kbps = two_pass
        cmd += ["-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{2 * kbps}k", "-pass", str(pass_no)]
        if passlog:
            cmd += ["-passlogfile", passlog]
    else:
        cmd += ["-crf", str(crf)]
    if two_pass and two_pass[0] == 1:
        # The null muxer never opens its file name, so os.devnull is only a placeholder (NUL on Windows).
        cmd += ["-an", "-map_metadata", "-1", "-map_chapters", "-1", "-f", "null", os.devnull]
        return cmd
    if include_audio:
        cmd += ["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ar", "48000", "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd += ["-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart", "-f", "mp4", out]
    return cmd


MAX_KBPS = 100_000  # far above any sensible clip; keeps x264's rate options in range for very short clips


def target_kbps(limit_mb: float, duration_s: float, audio_kbps: int = AUDIO_KBPS, scale: float = 1.0) -> int:
    duration_s = max(0.1, duration_s)
    kbps = ((limit_mb * 8192 * 0.95) / duration_s - audio_kbps) * scale
    return min(MAX_KBPS, max(MIN_KBPS, int(kbps)))


def kbps_for_size(size_bytes: int, duration_s: float, audio_kbps: int = AUDIO_KBPS, scale: float = 1.0) -> int:
    """Video bitrate that makes a file of `duration_s` about `scale` times `size_bytes` in size."""
    duration_s = max(0.1, duration_s)
    kbps = (size_bytes * 8 / 1024 / duration_s - audio_kbps) * scale
    return min(MAX_KBPS, max(MIN_KBPS, int(kbps)))


def build_two_pass_cmds(kbps: int, passlog: str, **kwargs) -> tuple[list[str], list[str]]:
    first = build_clip_cmd(two_pass=(1, kbps), passlog=passlog, **kwargs)
    second = build_clip_cmd(two_pass=(2, kbps), passlog=passlog, **kwargs)
    return first, second


def build_gif_to_mp4_cmd(
    ffmpeg: str,
    src: str,
    out: str,
    *,
    width: int,
    height: int,
    fps: float,
    aspect: str = "original",
    position: float = 0.5,
    preset: str = "medium",
    crf: int = 20,
    max_long_edge: int = 1920,
    edges: dict[str, float] | None = None,
) -> list[str]:
    cmd = _base(ffmpeg)
    cmd += ["-i", src]
    vf = build_filter_chain(width, height, aspect, position, max_long_edge, fps, edges=edges)
    if not vf:
        vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    cmd += ["-vf", vf, "-c:v", "libx264", "-profile:v", "high", "-preset", preset, "-crf", str(crf)]
    cmd += ["-pix_fmt", "yuv420p", "-an", "-map_metadata", "-1", "-map_chapters", "-1"]
    cmd += ["-movflags", "+faststart", "-f", "mp4", out]
    return cmd


# --- still images --------------------------------------------------------------------------------

# EXIF orientation -> filters that display the stored pixels upright (the same as Pillow's exif_transpose).
ORIENTATION_FILTERS = {
    2: ["hflip"],
    3: ["hflip", "vflip"],
    4: ["vflip"],
    5: ["transpose=cclock_flip"],  # transpose across the main diagonal
    6: ["transpose=clock"],
    7: ["transpose=clock_flip"],  # transverse
    8: ["transpose=cclock"],
}


def image_codec_args(out_format: str, quality: int = 92) -> list[str]:
    """Encoder and muxer arguments. image2pipe writes one frame to any file name, including `.part`."""
    if out_format == "JPEG":
        return ["-c:v", "mjpeg", "-pix_fmt", "yuvj420p", "-q:v", str(JPEG_QSCALE), "-f", "image2pipe"]
    if out_format == "PNG":
        return ["-c:v", "png", "-pred", "mixed", "-f", "image2pipe"]
    if out_format == "WEBP":
        return ["-c:v", "libwebp", "-quality", str(quality), "-f", "webp"]
    raise ValueError(f"cannot encode still images as {out_format}")


def build_image_cmd(
    ffmpeg: str,
    src: str,
    out: str,
    out_format: str,
    *,
    orientation: int = 1,
    crop: CropRect | None = None,
    size: tuple[int, int] | None = None,
    quality: int = 92,
    autorotate: bool = False,
) -> list[str]:
    """Re-encode one still image. Orientation is applied explicitly, so ffmpeg's own EXIF autorotation
    (ffmpeg 8 applies JPEG EXIF orientation on decode) is switched off to avoid rotating twice."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    if not autorotate:
        cmd.append("-noautorotate")
    cmd += ["-i", src, "-frames:v", "1"]
    filters = list(ORIENTATION_FILTERS.get(orientation, []))
    if crop:
        filters.append(f"crop={crop.w}:{crop.h}:{crop.x}:{crop.y}")
    if size:
        filters.append(f"scale={size[0]}:{size[1]}:flags=lanczos")
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += ["-map_metadata", "-1"] + image_codec_args(out_format, quality) + [out]
    return cmd


def build_frame_grab_cmd(
    ffmpeg: str, src: str, out: str, t: float, headers: dict[str, str] | None = None
) -> list[str]:
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    cmd += _headers_arg(headers)
    cmd += ["-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", "-map_metadata", "-1"]
    return cmd + image_codec_args("JPEG") + [out]


def build_thumb_cmd(ffmpeg: str, src: str, out: str, t: float = 0.0) -> list[str]:
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", src]
    cmd += ["-frames:v", "1", "-vf", "scale=320:-2", "-map_metadata", "-1"]
    return cmd + ["-c:v", "mjpeg", "-pix_fmt", "yuvj420p", "-q:v", "4", "-f", "image2pipe", out]

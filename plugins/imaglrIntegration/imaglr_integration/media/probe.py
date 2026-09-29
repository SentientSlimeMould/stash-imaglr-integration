# SPDX-License-Identifier: AGPL-3.0-only
"""ffprobe wrapper and parsing.

ffprobe reports 0x0 for animated WebP, because ffmpeg (8.0) cannot decode it; ProbeInfo then has
width == height == 0 and callers must treat the stream as undecodable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from fractions import Fraction

from .ffmpeg_run import run_tool

HDR_TRANSFERS = {"smpte2084", "arib-std-b67", "smpte428"}


@dataclass
class ProbeInfo:
    width: int
    height: int
    fps: float
    duration: float
    video_codec: str | None = None
    pix_fmt: str | None = None
    has_audio: bool = False
    audio_codec: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    rotation: int = 0
    side_data_types: list = field(default_factory=list)

    @property
    def display_size(self) -> tuple[int, int]:
        """Dimensions after ffmpeg's automatic rotation."""
        if self.rotation % 180 == 90:
            return self.height, self.width
        return self.width, self.height

    @property
    def has_alpha(self) -> bool:
        p = self.pix_fmt or ""
        return "yuva" in p or p.startswith(("rgba", "bgra", "argb", "abgr", "gbrap", "ya"))


def is_hdr(info: ProbeInfo) -> bool:
    if (info.color_transfer or "").lower() in HDR_TRANSFERS:
        return True
    if (info.color_primaries or "").lower() == "bt2020":
        return True
    return any("mastering" in t.lower() or "content light" in t.lower() for t in info.side_data_types)


def _frac(v) -> float:
    try:
        if isinstance(v, str) and "/" in v:
            num, den = v.split("/", 1)
            if float(den) == 0:
                return 0.0
            return float(Fraction(int(num), int(den)))
        return float(v)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0.0


def parse_probe(data: dict) -> ProbeInfo:
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise ValueError("no video stream")
    fmt = data.get("format") or {}
    duration = _frac(video.get("duration")) or _frac(fmt.get("duration"))
    fps = _frac(video.get("avg_frame_rate")) or _frac(video.get("r_frame_rate"))
    rotation = 0
    side_types: list[str] = []
    for sd in video.get("side_data_list") or []:
        side_types.append(str(sd.get("side_data_type", "")))
        if "rotation" in sd:
            try:
                rotation = int(round(float(sd["rotation"])))
            except (TypeError, ValueError):
                pass
    if not rotation:
        try:
            rotation = int(round(float((video.get("tags") or {}).get("rotate", 0))))
        except (TypeError, ValueError):
            rotation = 0
    return ProbeInfo(
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=fps,
        duration=duration,
        video_codec=video.get("codec_name"),
        pix_fmt=video.get("pix_fmt"),
        has_audio=audio is not None,
        audio_codec=audio.get("codec_name") if audio else None,
        color_transfer=video.get("color_transfer"),
        color_primaries=video.get("color_primaries"),
        rotation=rotation % 360,
        side_data_types=side_types,
    )


def build_probe_cmd(ffprobe: str, src: str, headers: dict[str, str] | None = None) -> list[str]:
    cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format"]
    if headers:
        cmd += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
    cmd.append(src)
    return cmd


def probe(ffprobe: str, src: str, headers: dict[str, str] | None = None, timeout: float = 60) -> ProbeInfo:
    """Probe a local path or an HTTP URL (with request headers, e.g. Stash's ApiKey)."""
    out = run_tool(build_probe_cmd(ffprobe, src, headers), timeout)
    return parse_probe(json.loads(out.decode(errors="replace") or "{}"))

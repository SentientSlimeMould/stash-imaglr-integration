# SPDX-License-Identifier: AGPL-3.0-only
"""Output file names: `{source-title-slug}_{in}-{out}.mp4` for clips, `{slug}.{ext}` for images."""

from __future__ import annotations

import re
import unicodedata


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len].rstrip("-")) or "clip"


def fmt_time_compact(seconds: float) -> str:
    """A time token that is safe in file names: 12.34 -> '12_3'."""
    return f"{seconds:.1f}".replace(".", "_")


def output_name(title: str, in_s: float, out_s: float, ext: str = "mp4") -> str:
    return f"{slugify(title)}_{fmt_time_compact(in_s)}-{fmt_time_compact(out_s)}.{ext}"


def image_output_name(title: str, ext: str) -> str:
    return f"{slugify(title)}.{ext.lower().lstrip('.')}"

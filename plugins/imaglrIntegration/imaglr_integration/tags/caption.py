# SPDX-License-Identifier: AGPL-3.0-only
"""Plain-text caption -> HTML body (reference spec §6.5)."""

from __future__ import annotations

import html
import re


def caption_to_html(text: str | None) -> str | None:
    """Escape, one <p> per paragraph, <br> for single newlines. None when blank: omit the body."""
    if text is None:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None
    paragraphs = [p.strip("\n") for p in re.split(r"\n\s*\n", text) if p.strip()]
    parts = []
    for p in paragraphs:
        lines = [html.escape(line.strip(), quote=False) for line in p.split("\n")]
        parts.append("<p>" + "<br>".join(lines) + "</p>")
    return "".join(parts)

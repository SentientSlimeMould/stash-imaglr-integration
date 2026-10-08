# SPDX-License-Identifier: AGPL-3.0-only
"""The plugin's simple options, edited in Stash under Settings → Plugins → Imaglr Integration.

Stash stores them in its config.yml and does not pass them to the plugin, so they are read over
GraphQL. A setting the user never saved is absent, so every default lives here, and booleans are
phrased so that "off" is the default (Stash shows an unsaved checkbox as unticked).
imaglr keys are NOT settings: they live in the plugin database (see blogs.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PLUGIN_ID = "imaglrIntegration"


@dataclass(frozen=True)
class Settings:
    queue_tag: str = "imaglr"
    done_tag: str = "imaglr-sent"
    exclude_patterns: str = "^AI_"
    keep_tag_case: bool = False
    default_clip_seconds: float = 15.0
    prepared_retention_days: int = 14
    clips_as_gif: bool = False  # new clips start as animated GIFs instead of videos
    gif_target_mb: float = 20.0  # the GIF export aims under this; imaglr's hard limit is 40 MB
    clips_hevc: bool = False  # new clips start as H.265 instead of H.264
    clip_max_edge: int | None = None  # new clips' picture size as a long edge (1280 = 720p, 854 = 480p); None = as the source


# Stash setting name -> (field, converter). Keep in step with `settings:` in imaglrIntegration.yml.
_FIELDS = {
    "tagQueue": ("queue_tag", str),
    "tagSent": ("done_tag", str),
    "tagsKeepCapitals": ("keep_tag_case", bool),
    "tagsNeverSuggested": ("exclude_patterns", str),
    "videoClipSize": ("clip_max_edge", "size"),
    "videoClipsAsGif": ("clips_as_gif", bool),
    "videoClipsAsHevc": ("clips_hevc", bool),
    "videoDefaultClipSeconds": ("default_clip_seconds", float),
    "videoGifTargetMb": ("gif_target_mb", float),
    "workingFilesKeepDays": ("prepared_retention_days", int),
}

GIF_HARD_LIMIT_MB = 40  # imaglr's ceiling for an image upload, which a GIF is
PICTURE_SIZES = {"1080": None, "720": 1280, "480": 854}  # the setting's words -> a long edge in px


def parse_size(value: Any) -> int | None:
    """"720" or "720p" -> 1280; anything else, including "1080", means as the source."""
    key = str(value).strip().lower().rstrip("p")
    if key not in PICTURE_SIZES:
        raise ValueError(value)
    return PICTURE_SIZES[key]


class SettingsError(ValueError):
    """A combination of settings the plugin can't work with; the message says how to fix it."""


def parse(raw: dict[str, Any] | None) -> Settings:
    values: dict[str, Any] = {}
    for key, (field, convert) in _FIELDS.items():
        value = (raw or {}).get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        try:
            if convert == "size":
                values[field] = parse_size(value)
                continue
            if convert is int:
                value = float(value)  # "14.0" from a text field
            values[field] = convert(value.strip() if isinstance(value, str) else value)
        except (TypeError, ValueError):
            continue
    if values.get("default_clip_seconds", 1) <= 0:
        values.pop("default_clip_seconds")
    if values.get("prepared_retention_days", 1) < 1:
        values.pop("prepared_retention_days")
    if not (1 <= values.get("gif_target_mb", 20) <= GIF_HARD_LIMIT_MB) or values.get("gif_target_mb", 20) != values.get("gif_target_mb", 20):
        values.pop("gif_target_mb", None)
    settings = Settings(**values)
    if settings.queue_tag.casefold() == settings.done_tag.casefold():
        raise SettingsError(
            "The plugin's Queue tag and Sent tag are the same. Give them different names in "
            "Settings → Plugins → Imaglr Integration."
        )
    return settings


def load(stash: Any) -> Settings:
    data = stash.gql(f'{{ configuration {{ plugins(include: ["{PLUGIN_ID}"]) }} }}')
    return parse((data["configuration"]["plugins"] or {}).get(PLUGIN_ID))

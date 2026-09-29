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


# Stash setting name -> (field, converter). Keep in step with `settings:` in imaglrIntegration.yml.
_FIELDS = {
    "queueTag": ("queue_tag", str),
    "doneTag": ("done_tag", str),
    "excludeTagPatterns": ("exclude_patterns", str),
    "keepTagCase": ("keep_tag_case", bool),
    "defaultClipSeconds": ("default_clip_seconds", float),
    "preparedRetentionDays": ("prepared_retention_days", int),
}


def parse(raw: dict[str, Any] | None) -> Settings:
    values: dict[str, Any] = {}
    for key, (field, convert) in _FIELDS.items():
        value = (raw or {}).get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        try:
            values[field] = convert(value.strip() if isinstance(value, str) else value)
        except (TypeError, ValueError):
            continue
    if values.get("default_clip_seconds", 1) <= 0:
        values.pop("default_clip_seconds")
    if values.get("prepared_retention_days", 1) < 1:
        values.pop("prepared_retention_days")
    return Settings(**values)


def load(stash: Any) -> Settings:
    data = stash.gql(f'{{ configuration {{ plugins(include: ["{PLUGIN_ID}"]) }} }}')
    return parse((data["configuration"]["plugins"] or {}).get(PLUGIN_ID))

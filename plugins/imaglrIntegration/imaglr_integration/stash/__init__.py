# SPDX-License-Identifier: AGPL-3.0-only
"""Talking to the Stash that runs the plugin: GraphQL client, queries and models."""

from .client import StashClient, StashError, base_url
from .models import Image, Marker, Scene, Tag, VisualFile
from .paths import HttpStream, LocalFile

__all__ = [
    "HttpStream",
    "Image",
    "LocalFile",
    "Marker",
    "Scene",
    "StashClient",
    "StashError",
    "Tag",
    "VisualFile",
    "base_url",
]

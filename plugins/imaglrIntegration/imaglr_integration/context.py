# SPDX-License-Identifier: AGPL-3.0-only
"""What every operation and task gets: the request, and lazily opened Stash, database and imaglr clients."""

from __future__ import annotations

import os
import re
from typing import Any

from .db import Database
from .imaglr import ImaglrClient
from .stash import StashClient

# Development only: point the plugin at a fake imaglr (dev/fake_imaglr.py). Unset in normal use.
IMAGLR_BASE_ENV = "IMAGLR_API_BASE"


class UserError(Exception):
    """An error whose message is safe and useful to show in the UI."""


def plugin_version(plugin_dir: str) -> str:
    try:
        with open(os.path.join(plugin_dir, "imaglrIntegration.yml"), encoding="utf-8") as f:
            for line in f:
                match = re.match(r"version:\s*(\S+)", line)
                if match:
                    return match.group(1)
    except OSError:
        pass
    return "unknown"


class Context:
    def __init__(self, request: dict[str, Any]):
        self.connection = request.get("server_connection") or {}
        self.args = request.get("args") or {}
        self.plugin_dir = self.connection.get("PluginDir") or os.path.dirname(os.path.dirname(__file__))
        self.data_dir = os.path.join(self.plugin_dir, "data")
        self.version = plugin_version(self.plugin_dir)
        self._stash: StashClient | None = None
        self._db: Database | None = None

    @property
    def stash(self) -> StashClient:
        if self._stash is None:
            self._stash = StashClient(self.connection)
        return self._stash

    @property
    def db(self) -> Database:
        if self._db is None:
            self._db = Database.in_data_dir(self.data_dir)
        return self._db

    def imaglr(self, blog: dict[str, Any]) -> ImaglrClient:
        kwargs = {}
        if os.environ.get(IMAGLR_BASE_ENV):
            kwargs["base_url"] = os.environ[IMAGLR_BASE_ENV]
        return ImaglrClient(blog["api_key"], self.version, **kwargs)

    def arg(self, name: str, kind: type = str, required: bool = True) -> Any:
        value = self.args.get(name)
        if value is None:
            if required:
                raise UserError(f"Missing argument: {name}")
            return None
        try:
            return kind(value)
        except (TypeError, ValueError):
            raise UserError(f"Bad value for {name}") from None

    def close(self) -> None:
        if self._db is not None:
            self._db.close()

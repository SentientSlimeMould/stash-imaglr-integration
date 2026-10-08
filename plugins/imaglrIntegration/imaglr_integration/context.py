# SPDX-License-Identifier: AGPL-3.0-only
"""What every operation and task gets: the request, and lazily opened Stash, database and imaglr clients."""

from __future__ import annotations

import ipaddress
import os
import urllib.parse
import re
from typing import Any

from . import log
from .db import Database
from .imaglr import ImaglrClient
from .stash import StashClient

# Development only: point the plugin at a fake imaglr (dev/fake_imaglr.py). Unset in normal use.
IMAGLR_BASE_ENV = "IMAGLR_API_BASE"
# Development only: the single-request limit above which a draft's files go up in pieces (bytes), so the
# chunked path can be exercised with small test files. Unset in normal use (the client's own 95 MB).
IMAGLR_REQUEST_LIMIT_ENV = "IMAGLR_SINGLE_REQUEST_LIMIT"


def imaglr_base_override() -> str | None:
    """The dev override, if set and safe: https anywhere, or plain http only to a loopback, private-network or
    bare (Docker service) host. Anything else is refused, because the request would carry the API key."""
    value = (os.environ.get(IMAGLR_BASE_ENV) or "").strip()
    if not value:
        return None
    parts = urllib.parse.urlsplit(value)
    host = parts.hostname or ""
    if parts.scheme == "https":
        return value
    if parts.scheme == "http":
        try:
            private = ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
        except ValueError:
            private = host == "localhost" or "." not in host  # a Compose service name
        if private:
            return value
    raise UserError(f"{IMAGLR_BASE_ENV} must be an https URL (or http to a local address); refusing {value!r}.")


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
        base = imaglr_base_override()
        if base:
            log.warning(f"{IMAGLR_BASE_ENV} is set: talking to {base} instead of imaglr.com (development only)")
            kwargs["base_url"] = base
            limit = (os.environ.get(IMAGLR_REQUEST_LIMIT_ENV) or "").strip()
            if limit.isdigit() and int(limit) > 0:  # only alongside the fake: never shrink real requests
                kwargs["single_request_limit"] = int(limit)
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

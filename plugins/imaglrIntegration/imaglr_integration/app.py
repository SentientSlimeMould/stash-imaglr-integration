# SPDX-License-Identifier: AGPL-3.0-only
"""Request dispatch: every call names a `mode` in its args.

Operations (runPluginOperation) must return quickly, because Stash kills the process when the HTTP
request ends. Anything slow runs as a task (runPluginTask), whose outcome is recorded in the plugin
database, since Stash reports every plugin task as FINISHED regardless of its result.
"""

import os
import platform
import re
import traceback

from . import log
from .stash import StashClient


class UserError(Exception):
    """An error whose message is safe and useful to show in the UI."""


class Context:
    def __init__(self, request):
        self.connection = request.get("server_connection") or {}
        self.args = request.get("args") or {}
        self.plugin_dir = self.connection.get("PluginDir") or os.path.dirname(os.path.dirname(__file__))
        self.data_dir = os.path.join(self.plugin_dir, "data")
        self._stash = None

    @property
    def stash(self):
        if self._stash is None:
            self._stash = StashClient(self.connection)
        return self._stash


def plugin_version(plugin_dir):
    try:
        with open(os.path.join(plugin_dir, "imaglrIntegration.yml"), encoding="utf-8") as f:
            for line in f:
                match = re.match(r"version:\s*(\S+)", line)
                if match:
                    return match.group(1)
    except OSError:
        pass
    return "unknown"


def op_ping(ctx):
    """Round trip check: plugin runs, can reach Stash, and can write its data folder."""
    data = ctx.stash.gql("{ version { version } systemStatus { ffmpegPath ffprobePath } }")
    os.makedirs(ctx.data_dir, exist_ok=True)
    probe = os.path.join(ctx.data_dir, ".write-test")
    with open(probe, "w") as f:
        f.write("ok")
    os.remove(probe)
    return {
        "pong": True,
        "plugin_version": plugin_version(ctx.plugin_dir),
        "python": platform.python_version(),
        "stash_version": data["version"]["version"],
        "ffmpeg": data["systemStatus"]["ffmpegPath"],
        "ffprobe": data["systemStatus"]["ffprobePath"],
        "echo": ctx.args.get("echo"),
    }


OPERATIONS = {
    "ping": op_ping,
}


def handle(request):
    """Returns (output, error) for Stash's raw-interface reply."""
    ctx = Context(request)
    mode = ctx.args.get("mode")
    handler = OPERATIONS.get(mode)
    if handler is None:
        return None, f"Unknown mode: {mode!r}"
    try:
        return handler(ctx), None
    except UserError as e:
        return None, str(e)
    except Exception as e:  # report, never crash without a reply
        log.error(f"{mode} failed: {e}\n{traceback.format_exc()}")
        return None, f"{mode} failed: {e}"

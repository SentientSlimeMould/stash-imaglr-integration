# SPDX-License-Identifier: AGPL-3.0-only
"""Request dispatch: every call names a `mode` in its args.

Operations (runPluginOperation) must return quickly, because Stash kills the process when the HTTP
request ends. Anything slow runs as a task (runPluginTask), whose outcome is recorded in the plugin
database, since Stash reports every plugin task as FINISHED regardless of its result.
"""

from __future__ import annotations

import os
import platform
import traceback
from typing import Any

from . import blog_ops, clip_ops, log, queue_ops, send_ops
from .settings import SettingsError
from .context import Context, imaglr_base_override, UserError, plugin_version

__all__ = ["handle", "OPERATIONS", "UserError", "plugin_version"]


def op_ping(ctx: Context) -> dict[str, Any]:
    """Round trip check: plugin runs, can reach Stash, and can write its data folder."""
    data = ctx.stash.gql("{ version { version } systemStatus { ffmpegPath ffprobePath } }")
    os.makedirs(ctx.data_dir, exist_ok=True)
    probe = os.path.join(ctx.data_dir, ".write-test")
    with open(probe, "w") as f:
        f.write("ok")
    os.remove(probe)
    return {
        "pong": True,
        "plugin_version": ctx.version,
        "python": platform.python_version(),
        "stash_version": data["version"]["version"],
        "ffmpeg": data["systemStatus"]["ffmpegPath"],
        "ffprobe": data["systemStatus"]["ffprobePath"],
        "imaglr_api_base": imaglr_base_override(),  # None in normal use
        "echo": ctx.args.get("echo"),
    }


OPERATIONS = {
    "ping": op_ping,
    **blog_ops.OPERATIONS,
    **queue_ops.OPERATIONS,
    **send_ops.OPERATIONS,
    **clip_ops.OPERATIONS,
    **send_ops.TASKS,
}


def handle(request: dict[str, Any]) -> tuple[Any, str | None]:
    """Returns (output, error) for Stash's raw-interface reply."""
    ctx = Context(request)
    mode = ctx.args.get("mode")
    handler = OPERATIONS.get(mode)
    if handler is None:
        return None, f"Unknown mode: {mode!r}"
    try:
        return handler(ctx), None
    except (UserError, SettingsError) as e:
        return None, log.redact(str(e))
    except Exception as e:  # report, never crash without a reply
        log.error(f"{mode} failed: {e}\n{traceback.format_exc()}")
        return None, log.redact(f"{mode} failed: {e}")
    finally:
        ctx.close()

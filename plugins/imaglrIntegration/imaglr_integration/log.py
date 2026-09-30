# SPDX-License-Identifier: AGPL-3.0-only
"""Stash plugin log and progress protocol, written to stderr.

Each line is "\\x01<level>\\x02<message>". Every line of a multi-line message is prefixed, because
Stash logs an unprefixed line at error level. Lines are capped well below the 64 KB limit that
breaks Stash v0.31.1's log reader, and anything that looks like an imaglr key is masked.
"""

import re
import sys

MAX_LINE = 4000
_KEY = re.compile(r"pbk_[^\s\"',;]+")
_SECRETS = []  # exact strings that must never appear in a log line or an error message (Stash's API key, session cookie)


def register_secret(value):
    """Mask this value wherever text leaves the plugin (logs, error details, operation replies)."""
    if value and len(str(value)) >= 8 and str(value) not in _SECRETS:
        _SECRETS.append(str(value))


def redact(text):
    text = _KEY.sub("pbk_***", str(text))
    for secret in _SECRETS:
        text = text.replace(secret, "***")
    return text


def _emit(level, message):
    for line in redact(str(message)).splitlines() or [""]:
        if len(line) > MAX_LINE:
            line = line[:MAX_LINE] + " …(truncated)"
        sys.stderr.write(f"\x01{level}\x02{line}\n")
    sys.stderr.flush()


def trace(message):
    _emit("t", message)


def debug(message):
    _emit("d", message)


def info(message):
    _emit("i", message)


def warning(message):
    _emit("w", message)


def error(message):
    _emit("e", message)


def progress(fraction):
    """Report task progress, 0.0 to 1.0. Shown on Stash's job queue for tasks only."""
    sys.stderr.write(f"\x01p\x02{min(max(float(fraction), 0.0), 1.0)}\n")
    sys.stderr.flush()

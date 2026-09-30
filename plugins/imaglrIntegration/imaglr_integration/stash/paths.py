# SPDX-License-Identifier: AGPL-3.0-only
"""Where to read a Stash file from, and plain HTTP downloads from Stash.

The plugin runs inside Stash, so the local paths Stash reports are normally readable as they are. When a
file isn't readable (or is a zip member) the source is Stash's own HTTP URL instead: `paths.image` for
images, `paths.stream` for scenes. Both serve the original file.
"""

from __future__ import annotations

import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .client import StashError
from .models import Image, Scene


@dataclass(frozen=True)
class LocalFile:
    path: str


@dataclass(frozen=True)
class HttpStream:
    url: str


def _readable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.R_OK)


def without_apikey(url: str) -> str:
    """Stash puts `?apikey=<its API key>` on stream URLs. Requests to Stash are authenticated with a header
    instead, so the key is dropped from the URL: ffmpeg prints the URL in its errors and in `ps`."""
    parts = urllib.parse.urlsplit(url)
    if "apikey" not in parts.query.lower():
        return url
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if k.lower() != "apikey"]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def resolve_source(
    file_path: str | None,
    url: str | None,
    in_zip: bool = False,
    readable=_readable,
) -> LocalFile | HttpStream | None:
    if file_path and not in_zip and readable(file_path):
        return LocalFile(file_path)
    if url:
        return HttpStream(without_apikey(url))
    return None


def scene_source(scene: Scene) -> LocalFile | HttpStream | None:
    f = scene.primary_file
    return resolve_source(f.path if f else None, scene.stream_url)


def image_source(image: Image) -> LocalFile | HttpStream | None:
    """Uses the image's first visual file, as Stash's own `paths.image` does."""
    f = image.primary_file
    return resolve_source(f.path if f else None, image.image_url, in_zip=bool(f and f.zip_path))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The request carries Stash's credentials, which must not follow a redirect to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(url: str, dest: str, headers: dict[str, str], timeout: float = 60, context=None) -> str:
    """Download url to dest via dest + ".part", so a partial file never has the final name.
    Returns the response's Content-Type. headers carry Stash auth (see api.auth_headers)."""
    part = dest + ".part"
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=context))
    try:
        with opener.open(req, timeout=timeout) as resp, open(part, "wb") as fh:
            shutil.copyfileobj(resp, fh, 1 << 16)
            content_type = resp.headers.get("Content-Type") or ""
    except (urllib.error.URLError, OSError) as e:
        try:
            os.remove(part)
        except OSError:
            pass
        if isinstance(e, urllib.error.HTTPError):
            raise StashError(f"download from Stash failed: HTTP {e.code}") from None
        raise StashError(f"download from Stash failed: {getattr(e, 'reason', e)}") from None
    os.replace(part, dest)
    return content_type

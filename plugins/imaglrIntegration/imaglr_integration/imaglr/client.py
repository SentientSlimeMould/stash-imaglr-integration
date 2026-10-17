# SPDX-License-Identifier: AGPL-3.0-only
"""imaglr API v2 client: create drafts, then optionally queue or publish them; read feeds and posts so the user
can browse imaglr and save the posts they choose; reblog a post.

The allowlist below is the complete set of endpoints this plugin may ever call (spec Amendment 6, extended
2026-10-08 with imaglr's chunked uploads and 2026-10-17 with reading and reblogging, which imaglr approved for
browsing and saving chosen posts). tests/python/test_imaglr_allowlist.py fails if any other route appears in
this module. Every API call goes through `_request`, which refuses anything not on the list, and redirects are
never followed. imaglr's "next page" links are followed only after they are matched back to an allowed route.

Media files (the pictures and videos of a post) come from imaglr's CDN through `fetch_media`, the one other
gateway: https to imaglr's own hosts only, never with the API key, never following a redirect.

Requests pass through an edge that refuses any request body over 100 MB (a bare HTML 413, measured). A draft
whose files would exceed that is sent the way imaglr documents for large files: each file goes up in 50 MB
pieces through /uploads, and the draft then references the upload ids instead of carrying the bytes.
"""

from __future__ import annotations

import http.client
import json
import math
import mimetypes
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Sequence

from .errors import ImaglrError, field_from_code

ALLOWED_ENDPOINTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/user/info"),
        ("GET", "/user/limits"),
        ("POST", "/drafts"),
        ("POST", "/drafts/{id}/publish"),
        ("POST", "/drafts/{id}/queue"),
        # large files, in pieces (see the module docstring)
        ("POST", "/uploads"),
        ("PUT", "/uploads/{id}/chunks/{index}"),
        ("POST", "/uploads/{id}/complete"),
        ("DELETE", "/uploads/{id}"),
        # reading: browsing imaglr and saving the posts the user chooses
        ("GET", "/user/feed"),
        ("GET", "/user/likes"),
        ("GET", "/tagged"),
        ("GET", "/profiles/{name}"),
        ("GET", "/profiles/{name}/posts"),
        ("GET", "/posts/{id}"),
        # reblogging a post to one of the user's blogs (instead of re-uploading a saved copy)
        ("POST", "/posts/{id}/repost"),
    }
)
PAGE_SIZE = 20  # posts per page while browsing (imaglr allows 1-50)
# Where a post's pictures and videos are served from: imaglr.com itself or its numbered CDN hosts, over https.
MEDIA_HOST = re.compile(r"^(?:cdn\d{0,3}\.)?imaglr\.com$")
MEDIA_TIMEOUT = 120.0

DEFAULT_BASE_URL = "https://imaglr.com/api/v2"
MAX_FILES_PER_DRAFT = 10  # imaglr: "up to 10 files per post"
DEFAULT_TIMEOUT = 30.0
UPLOAD_TIMEOUT = 1800.0  # large videos on a home upload link
CHUNK_SIZE = 1024 * 1024
# One request may carry at most 100 MB through imaglr's edge; this is what a single multipart draft request
# may total (files plus fields), leaving room for the multipart framing.
SINGLE_REQUEST_LIMIT = 95 * 1024 * 1024
PIECE_ATTEMPTS = 3  # a piece that fails for a passing reason is simply sent again

# The formats imaglr accepts; mimetypes does not know all of them on every Python we support.
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
}

ProgressCallback = Callable[[float], None]


class DisallowedEndpoint(RuntimeError):
    pass


@dataclass
class DraftResult:
    id: str
    url: str | None
    tags: list[str]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class Page:
    """One page of posts and imaglr's link to the next (None at the end). The link is opaque: pass it back
    unchanged to read on."""
    posts: list[dict[str, Any]]
    next: str | None


class UploadCancelled(Exception):
    """Raised from inside the request body when the caller's should_cancel() says stop; the connection is
    dropped before imaglr has a complete body, so no draft is created."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect could reach a route outside the allowlist (and would carry the key), so it is an error."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ImaglrClient:
    def __init__(
        self,
        api_key: str,
        version: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        upload_timeout: float = UPLOAD_TIMEOUT,
        single_request_limit: int = SINGLE_REQUEST_LIMIT,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._upload_timeout = upload_timeout
        self._single_request_limit = single_request_limit
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            # imaglr's edge rejects urllib's default agent with a bare 403.
            "User-Agent": f"stash-imaglr-integration/{version}",
            "Accept": "application/json",
        }
        self._opener = urllib.request.build_opener(_NoRedirect)

    # ---- the single gateway --------------------------------------------------------------
    def _request(
        self,
        method: str,
        route: str,
        route_args: dict[str, str] | None = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        method = method.upper()
        if (method, route) not in ALLOWED_ENDPOINTS:
            raise DisallowedEndpoint(f"{method} {route} is not permitted")
        # Quote every path argument whole, so an id can never add path segments.
        path = route.format(**{k: urllib.parse.quote(v, safe="") for k, v in (route_args or {}).items()})
        if query:
            path += "?" + urllib.parse.urlencode(query)
        req = urllib.request.Request(
            self._base_url + path, data=data, method=method, headers={**self._headers, **(headers or {})}
        )
        try:
            try:
                with self._opener.open(req, timeout=timeout or self._timeout) as resp:
                    status, resp_headers, body = resp.status, resp.headers, resp.read()
            except urllib.error.HTTPError as e:
                try:
                    status, resp_headers, body = e.code, e.headers, e.read()
                finally:
                    e.close()
        except (OSError, http.client.HTTPException) as e:
            reason = getattr(e, "reason", None) or e
            err = ImaglrError("network_error", detail=f"{type(e).__name__}: {reason}")
            # If the whole body went out, the server may well have committed the request (a draft) before the
            # reply was lost: the caller must not simply retry.
            err.body_sent = bool(getattr(data, "length", 0)) and getattr(data, "sent", 0) >= data.length
            raise err from e
        return _parse(status, resp_headers, body)

    def _route_for(self, href: str) -> tuple[str, dict[str, str], dict[str, str]]:
        """Match one of imaglr's "next page" links back to an allowed GET route: (route, its arguments, the
        query). A link to anywhere else, or to another host, is refused."""
        base = urllib.parse.urlsplit(self._base_url)
        link = urllib.parse.urlsplit(href)
        if (link.scheme, link.netloc) != (base.scheme, base.netloc) or not link.path.startswith(base.path + "/"):
            raise DisallowedEndpoint("a next-page link that leaves imaglr's API is not followed")
        rest = link.path[len(base.path):]
        for method, route in ALLOWED_ENDPOINTS:
            if method != "GET":
                continue
            pattern = "^" + re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", re.escape(route)) + "$"
            match = re.match(pattern, rest)
            if match:
                args = {k: urllib.parse.unquote(v) for k, v in match.groupdict().items()}
                return route, args, dict(urllib.parse.parse_qsl(link.query, keep_blank_values=True))
        raise DisallowedEndpoint(f"GET {rest} is not permitted")

    def _page(self, route: str, route_args: dict[str, str] | None, query: dict[str, str], next_link: str | None) -> Page:
        """A page of posts from a list route, or the page `next_link` points at (which must be the same route)."""
        if next_link:
            linked, args, linked_query = self._route_for(next_link)
            if linked != route or args != (route_args or {}):
                raise DisallowedEndpoint("that next-page link belongs to another list")
            query = linked_query
        response = self._request("GET", route, route_args, query=query)
        posts = [p for p in response.get("posts") or [] if isinstance(p, dict) and p.get("id") is not None]
        links = response.get("_links") if isinstance(response.get("_links"), dict) else {}
        nxt = links.get("next") if isinstance(links.get("next"), dict) else {}
        href = nxt.get("href")
        return Page(posts, href if isinstance(href, str) and href else None)

    # ---- the permitted operations ----------------------------------------------------------
    def feed(self, next_link: str | None = None, limit: int = PAGE_SIZE) -> Page:
        """The user's dashboard feed."""
        return self._page("/user/feed", None, {"limit": str(limit)}, next_link)

    def likes(self, next_link: str | None = None, limit: int = PAGE_SIZE) -> Page:
        """Posts the user has liked, as imaglr lists them."""
        return self._page("/user/likes", None, {"limit": str(limit)}, next_link)

    def tagged(self, tag: str, next_link: str | None = None, limit: int = PAGE_SIZE) -> Page:
        """Posts carrying a tag."""
        return self._page("/tagged", None, {"tag": tag, "limit": str(limit)}, next_link)

    def profile(self, name: str) -> dict[str, Any]:
        """A creator's profile."""
        response = self._request("GET", "/profiles/{name}", {"name": name})
        return response.get("profile") if isinstance(response.get("profile"), dict) else response

    def profile_posts(self, name: str, next_link: str | None = None, limit: int = PAGE_SIZE) -> Page:
        """A creator's posts, newest first."""
        return self._page("/profiles/{name}/posts", {"name": name}, {"limit": str(limit)}, next_link)

    def post(self, post_id: str | int) -> dict[str, Any]:
        """One post."""
        response = self._request("GET", "/posts/{id}", {"id": _draft_id(post_id)})
        post = response.get("post") if isinstance(response.get("post"), dict) else response
        if not isinstance(post, dict) or post.get("id") is None:
            raise ImaglrError("unexpected_response", detail="no post in response")
        return post

    def repost(self, post_id: str | int, body_html: str | None = None, tags: Sequence[str] = ()) -> dict[str, Any]:
        """Reblog a post to this key's blog, straight away. Returns imaglr's response."""
        fields = [("tags[]", str(t)) for t in tags]
        if body_html:
            fields.insert(0, ("body", body_html))
        data = urllib.parse.urlencode(fields).encode("utf-8")
        return self._request("POST", "/posts/{id}/repost", {"id": _draft_id(post_id)}, data=data,
                             headers={"Content-Type": "application/x-www-form-urlencoded"})

    def user_info(self) -> dict[str, Any]:
        return self._request("GET", "/user/info")

    def user_limits(self) -> dict[str, Any]:
        return self._request("GET", "/user/limits")

    def create_draft(
        self,
        media: Sequence[Any],
        tags: Sequence[str] = (),
        body_html: str | None = None,
        progress_cb: ProgressCallback | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> DraftResult:
        """One draft carrying 1..MAX_FILES_PER_DRAFT files, in the given order, streamed from disk.

        Each media item is a path, or (path, content type) to override the type guessed from its extension.
        `progress_cb` receives the fraction of the bytes sent so far, ending at 1.0. `should_cancel` is polled
        between chunks; True aborts with UploadCancelled before anything is created.

        Small enough, the files travel inside the one draft request. Otherwise every file is first sent in
        pieces through /uploads (all of them, so the draft keeps the given order) and the request carries only
        their ids: nothing then exceeds the edge's limit on a single request.
        """
        if not media or len(media) > MAX_FILES_PER_DRAFT:
            raise ValueError(f"a draft needs 1 to {MAX_FILES_PER_DRAFT} files")
        files = []
        for item in media:
            path, content_type = item if isinstance(item, tuple) else (item, None)
            path = os.fspath(path)
            if path.endswith(".part"):
                raise ValueError("refusing to upload a partial file")
            files.append((path, content_type or guess_content_type(path)))
        fields = [("tags[]", str(t)) for t in tags]
        if body_html:
            fields.insert(0, ("body", body_html))
        if sum(os.path.getsize(p) for p, _ in files) <= self._single_request_limit:
            body = MultipartBody(fields, files, progress_cb, should_cancel)
            headers = {"Content-Type": body.content_type, "Content-Length": str(body.length)}
            response = self._request("POST", "/drafts", data=body, headers=headers, timeout=self._upload_timeout)
            return parse_draft_response(response)
        # in pieces: the progress spans every file's bytes
        total = sum(os.path.getsize(p) for p, _ in files)
        done = 0
        upload_ids: list[str] = []
        for path, content_type in files:
            size = os.path.getsize(path)

            def piece_progress(sent: int, done: int = done) -> None:
                if progress_cb:
                    progress_cb(min(1.0, (done + sent) / total))

            try:
                upload_ids.append(self.upload_in_pieces(path, piece_progress, should_cancel))
            except UploadCancelled:
                for uid in upload_ids:
                    self._discard_upload(uid)
                raise
            done += size
        body = MultipartBody(fields + [("uploads[]", uid) for uid in upload_ids], [], None, should_cancel)
        headers = {"Content-Type": body.content_type, "Content-Length": str(body.length)}
        response = self._request("POST", "/drafts", data=body, headers=headers, timeout=self._upload_timeout)
        if progress_cb:
            progress_cb(1.0)
        return parse_draft_response(response)

    def upload_in_pieces(self, path: str, progress_cb: Callable[[int], None] | None = None,
                         should_cancel: Callable[[], bool] | None = None) -> str:
        """Send one file through imaglr's chunked upload and return the upload id to reference from a draft.
        Pieces are chunk_size bytes as imaglr asks (50 MB), each its own request; a piece that fails for a
        passing reason is sent again. The upload is discarded if the caller cancels."""
        size = os.path.getsize(path)
        started = self._request("POST", "/uploads", data=urllib.parse.urlencode(
            {"filename": os.path.basename(path), "size": str(size)}).encode("ascii"),
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        upload = started.get("upload") if isinstance(started.get("upload"), dict) else started
        upload_id = str(upload.get("id") or "")
        piece_size = int(upload.get("chunk_size") or 0)
        if not upload_id or piece_size <= 0:
            raise ImaglrError("unexpected_response", detail="no upload id or chunk size in response")
        pieces = max(1, math.ceil(size / piece_size))
        sent_before = 0
        for index in range(pieces):
            if should_cancel and should_cancel():
                self._discard_upload(upload_id)
                raise UploadCancelled()
            length = min(piece_size, size - index * piece_size)
            for attempt in range(PIECE_ATTEMPTS):
                piece = FilePiece(path, index * piece_size, length, lambda n, b=sent_before: progress_cb(b + n) if progress_cb else None)
                try:
                    self._request("PUT", "/uploads/{id}/chunks/{index}", {"id": upload_id, "index": str(index)},
                                  data=piece, headers={"Content-Type": "application/octet-stream",
                                                       "Content-Length": str(length)},
                                  timeout=self._upload_timeout)
                    break
                except ImaglrError as e:
                    if e.code not in ("network_error", "server_error") or attempt == PIECE_ATTEMPTS - 1:
                        raise
            sent_before += length
        self._request("POST", "/uploads/{id}/complete", {"id": upload_id}, timeout=self._upload_timeout)
        return upload_id

    def _discard_upload(self, upload_id: str) -> None:
        try:
            self._request("DELETE", "/uploads/{id}", {"id": upload_id})
        except ImaglrError:
            pass  # unused uploads expire on their own

    def publish_draft(self, draft_id: str | int) -> dict[str, Any]:
        """Publish a draft now. Returns imaglr's `response` object as sent (shape not yet confirmed)."""
        return self._request("POST", "/drafts/{id}/publish", {"id": _draft_id(draft_id)})

    def queue_draft(self, draft_id: str | int) -> dict[str, Any]:
        """Move a draft into the publish queue. Returns imaglr's `response` object as sent."""
        return self._request("POST", "/drafts/{id}/queue", {"id": _draft_id(draft_id)})


class MediaRefused(ValueError):
    """A media address that isn't imaglr's own, or a file over the size it may be."""


def media_url_ok(url: str, extra_host: str | None = None) -> bool:
    """True for an https address on imaglr's own hosts; `extra_host` (scheme://host:port, development only)
    allows the fake server's address too."""
    parts = urllib.parse.urlsplit(url)
    if extra_host:
        extra = urllib.parse.urlsplit(extra_host)
        if (parts.scheme, parts.netloc) == (extra.scheme, extra.netloc):
            return True
    return parts.scheme == "https" and bool(MEDIA_HOST.match(parts.hostname or "")) and not parts.username


def fetch_media(url: str, dest: str, version: str, *, max_bytes: int, extra_host: str | None = None,
                should_cancel: Callable[[], bool] | None = None, timeout: float = MEDIA_TIMEOUT) -> tuple[int, str | None]:
    """Download a post's picture or video to `dest` (through `dest`.part, renamed when complete) and return
    (bytes, content type). Only imaglr's media hosts, never with the API key, never following a redirect, and
    never more than `max_bytes`."""
    if not media_url_ok(url, extra_host):
        raise MediaRefused("that file isn't on imaglr")
    req = urllib.request.Request(url, headers={"User-Agent": f"stash-imaglr-integration/{version}"})
    opener = urllib.request.build_opener(_NoRedirect)
    part = f"{dest}.{os.getpid()}.part"  # two previews of the same file at once must not share a part file
    written = 0
    try:
        with opener.open(req, timeout=timeout) as resp:
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise MediaRefused(f"the file is over {max_bytes // 1048576} MB")
            content_type = resp.headers.get_content_type() if resp.headers.get("Content-Type") else None
            with open(part, "wb") as f:
                while True:
                    if should_cancel and should_cancel():
                        raise UploadCancelled()
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise MediaRefused(f"the file is over {max_bytes // 1048576} MB")
                    f.write(chunk)
        os.replace(part, dest)
    except urllib.error.HTTPError as e:
        e.close()
        _remove_quietly(part)
        raise ImaglrError("not_found" if e.code == 404 else "server_error" if e.code >= 500 else "unknown",
                          detail=f"HTTP {e.code} for a media file", http_status=e.code) from None
    except (OSError, http.client.HTTPException) as e:
        _remove_quietly(part)
        raise ImaglrError("network_error", detail=f"{type(e).__name__}: {getattr(e, 'reason', None) or e}") from e
    except BaseException:
        _remove_quietly(part)
        raise
    return written, content_type


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _draft_id(draft_id: str | int) -> str:
    value = str(draft_id).strip()
    if not value:
        raise ValueError("a draft id is required")
    return value


def guess_content_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return CONTENT_TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"


class MultipartBody:
    """A multipart/form-data body that urllib sends chunk by chunk, reading files from disk as it goes.

    Iterating yields the whole body again, so it is exactly `length` bytes each time; file sizes are
    taken up front for the Content-Length, and a file that shrinks meanwhile aborts the upload.
    """

    def __init__(
        self,
        fields: Sequence[tuple[str, str]],
        files: Sequence[tuple[str, str]],
        progress_cb: ProgressCallback | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ):
        self.boundary = "stash-imaglr-" + secrets.token_hex(16)
        self.content_type = f"multipart/form-data; boundary={self.boundary}"
        self._progress_cb = progress_cb
        self._should_cancel = should_cancel
        self.sent = 0  # bytes handed to the connection so far (this attempt)
        self._parts: list[bytes | tuple[str, int]] = []
        for name, value in fields:
            self._parts.append(self._head(name) + value.encode("utf-8") + b"\r\n")
        for path, content_type in files:
            self._parts.append(self._head("media[]", os.path.basename(path), content_type))
            self._parts.append((path, os.path.getsize(path)))
            self._parts.append(b"\r\n")
        self._parts.append(f"--{self.boundary}--\r\n".encode("ascii"))
        self.length = sum(len(p) if isinstance(p, bytes) else p[1] for p in self._parts)

    def _head(self, name: str, filename: str | None = None, content_type: str | None = None) -> bytes:
        disposition = f'form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{_quote_filename(filename)}"'
        lines = [f"--{self.boundary}", f"Content-Disposition: {disposition}"]
        if content_type:
            lines.append(f"Content-Type: {content_type}")
        return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")

    def __iter__(self) -> Iterator[bytes]:
        self.sent = 0
        for part in self._parts:
            chunks = (part,) if isinstance(part, bytes) else _file_chunks(*part)
            for chunk in chunks:
                if self._should_cancel and self.sent < self.length and self._should_cancel():
                    raise UploadCancelled()
                yield chunk
                self.sent += len(chunk)
                if self._progress_cb:
                    self._progress_cb(min(1.0, self.sent / self.length))


class FilePiece:
    """`length` bytes of a file from `offset`, as a request body urllib sends chunk by chunk; reports the bytes
    sent so far to `on_progress`. Iterating again sends the same bytes again (a retried piece)."""

    def __init__(self, path: str, offset: int, length: int, on_progress: Callable[[int], None] | None = None):
        self._path, self._offset, self.length, self._on_progress = path, offset, length, on_progress
        self.sent = 0

    def __iter__(self) -> Iterator[bytes]:
        self.sent = 0
        with open(self._path, "rb") as f:
            f.seek(self._offset)
            remaining = self.length
            while remaining:
                chunk = f.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise OSError(f"{os.path.basename(self._path)} changed size during upload")
                remaining -= len(chunk)
                yield chunk
                self.sent += len(chunk)
                if self._on_progress:
                    self._on_progress(self.sent)


def _quote_filename(name: str) -> str:
    return "".join("_" if c in '"\\\r\n' else c for c in name)


def _file_chunks(path: str, size: int) -> Iterator[bytes]:
    with open(path, "rb") as f:
        remaining = size
        while remaining:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                raise OSError(f"{os.path.basename(path)} changed size during upload")
            remaining -= len(chunk)
            yield chunk


def _parse(status: int, headers: Any, raw: bytes) -> dict[str, Any]:
    retry_after = None
    ra = headers.get("Retry-After") if headers is not None else None
    if ra:
        try:
            retry_after = float(ra)
        except ValueError:
            pass
        if retry_after is not None and not (0 <= retry_after < math.inf):
            retry_after = None
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        # Not an imaglr envelope, e.g. the edge refusing a request before it reaches the API.
        if status >= 500:
            raise ImaglrError("server_error", detail=f"HTTP {status}", http_status=status)
        if status == 429:
            raise ImaglrError("rate_limited", http_status=429, retry_after=retry_after)
        if status == 413:  # a proxy in front of the API refusing the request body as too big
            raise ImaglrError("file_too_large", detail="HTTP 413: upload too large", http_status=413)
        if status in (401, 403):
            raise ImaglrError(
                "not_authenticated", detail=f"HTTP {status} without an imaglr response", http_status=status
            )
        raise ImaglrError("unknown", detail=f"HTTP {status} non-JSON body", http_status=status)
    errors = data.get("errors")
    if errors:
        first = errors[0] if isinstance(errors, list) and errors else {}
        code = str(first.get("code") or "unknown") if isinstance(first, dict) else "unknown"
        detail = str(first.get("detail") or "") if isinstance(first, dict) else str(first)
        fld = first.get("field") if isinstance(first, dict) else None
        raise ImaglrError(
            code,
            detail=detail,
            http_status=status,
            retry_after=retry_after,
            field=fld or field_from_code(code),
        )
    if status >= 400:
        if status == 429:
            raise ImaglrError("rate_limited", http_status=429, retry_after=retry_after)
        if status >= 500:
            raise ImaglrError("server_error", detail=f"HTTP {status}", http_status=status)
        raise ImaglrError("unknown", detail=f"HTTP {status}", http_status=status)
    response = data.get("response")
    return response if isinstance(response, dict) else {}


def parse_draft_response(response: dict[str, Any]) -> DraftResult:
    """The live API returns the draft as a post object at `response.post`; the rest is defensive."""
    post = response.get("post") if isinstance(response.get("post"), dict) else None
    if post is None and response.get("id") is not None:
        post = response
    if post is None:
        post = response.get("draft") if isinstance(response.get("draft"), dict) else None
    if not post or post.get("id") is None:
        raise ImaglrError("unexpected_response", detail="no post id in response")
    tags: list[str] = []
    for t in post.get("tags") or []:
        if isinstance(t, str):
            tags.append(t)
        elif isinstance(t, dict) and t.get("name"):
            tags.append(str(t["name"]))
    url = post.get("url")
    return DraftResult(id=str(post["id"]), url=url if isinstance(url, str) else None, tags=tags, raw=post)

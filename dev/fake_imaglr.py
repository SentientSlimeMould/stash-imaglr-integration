#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""A fake imaglr API v2 for local testing. Development only; never shipped with the plugin.

Implements the routes the plugin may call, with the same response envelope shape (error texts are this
fake's own words; the plugin only ever branches on error codes): GET /user/info, GET /user/limits,
POST /drafts, POST /drafts/{id}/publish, POST /drafts/{id}/queue, and imaglr's chunked uploads
(POST /uploads, PUT /uploads/{id}/chunks/{index}, POST /uploads/{id}/complete, DELETE /uploads/{id}) with a
small chunk size (CHUNK_SIZE below) so test files exercise them. A draft made from uploads[] is marked
"chunked" in the listing.
Anything else returns 404 and is logged loudly, so a stray call is easy to spot.

Uploads are saved under <state dir>/drafts/<id>/ and listed at http://127.0.0.1:8900/.

The API key chooses the scenario (keys look like pbk_<scenario>|anything):
  pbk_blogone|...    a working supporter blog called "blog-one" (pbk_blogtwo|... gives "blog-two")
  pbk_invalid|...    401 invalid_key
  pbk_noscope|...    403 insufficient_scope on drafts (info still works)
  pbk_premium|...    403 premium_required on drafts
  pbk_suspended|...  403 account_suspended
  pbk_ratelimit|...  first POST /drafts gets 429 rate_limited with Retry-After: 2
  pbk_flaky|...      first POST /drafts gets 500 server_error
  pbk_nopublish|...  drafts work, publish and queue get 500 server_error
  pbk_rejected|...   422 content_rejected
  pbk_toolarge|...   first POST /drafts gets 422 file_too_large
Tags named "banned" or starting with "banned-" are silently dropped, like imaglr does.

Browsing (for saving posts into Stash): GET /user/feed, /user/likes, /tagged?tag=, /profiles/{name},
/profiles/{name}/posts, /profiles/{name}/following and /posts/{id} serve a fixed catalogue of made-up posts by made-up creators, paged with
a cursor and absolute next links like imaglr's; POST /posts/{id}/repost records a reblog (listed on the index
page). The posts' pictures, GIFs and videos are served without a key from /media/, like imaglr's CDN; they are
generated on first request (PNG in pure Python, GIF and MP4 with ffmpeg when it is on PATH).

Run: python3 dev/fake_imaglr.py [port] [state dir]   (the compose file runs it as `fake-imaglr`)
"""

import email.parser
import email.policy
import html
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8900
STATE = sys.argv[2] if len(sys.argv) > 2 else "/tmp/fake-imaglr"
LOCK = threading.Lock()
SEEN_FIRST_POST = set()
DRAFTS = {}  # id -> record
UPLOADS = {}  # id -> {"filename", "size", "chunks": {index: bytes}, "total", "status"}
CHUNK_SIZE = 512 * 1024  # imaglr's is 50 MB; small here so a few-MB test clip goes in several pieces
REPOSTS = []  # (blog, post id)

# ---- the browse catalogue -------------------------------------------------------------------------------
CREATORS = ("sunny-days", "city-lights", "ocean-views", "mountain-trails")
LIKED = (7000, 7002, 7003, 7010)
SPECIAL = {
    # id: (creator, media kinds, tags, caption); everything else follows a pattern below
    7000: ("sunny-days", ["image"], ["sunset", "beach", "imaglr", "Test Performer"], "Golden hour on the shore"),
    7001: ("city-lights", ["video"], ["night", "city"], "Night drive through the centre"),
    7002: ("ocean-views", ["image", "image", "video"], ["ocean", "Test Studio"], "Three from the harbour"),
    7003: ("mountain-trails", ["gif"], ["hiking"], "Switchbacks"),
    7005: ("city-lights", [], ["thoughts"], "A text post with nothing to save"),
}


def catalogue(host):
    """Every post, newest first, with media addresses on this server (like imaglr's CDN)."""
    base = f"http://{host}"
    posts = []
    for n in range(26):
        pid = 7000 + n
        creator, kinds, tags, caption = SPECIAL.get(pid, (
            CREATORS[n % len(CREATORS)], ["video" if n % 3 == 0 else "image"], [["sunset"], ["city"], ["ocean"], ["hiking"]][n % 4],
            f"Post number {n}"))
        media = []
        for k, kind in enumerate(kinds, 1):
            name, mime = {"image": (f"{pid}-{k}.png", "image/png"), "gif": (f"{pid}-{k}.gif", "image/gif"),
                          "video": (f"{pid}-{k}.mp4", "video/mp4")}[kind]
            media.append({"url": f"{base}/media/{name}", "thumb": f"{base}/media/{pid}-{k}-thumb.png" if kind == "video" else None,
                          "kind": "video" if kind == "video" else "image", "mime": mime, "width": 320, "height": 240, "alt": None})
        post = {
            "id": pid, "url": f"https://imaglr.example/post/{pid}", "type": "video" if any(m["kind"] == "video" for m in media) else "image" if media else "text",
            "profile": {"name": creator, "url": f"https://imaglr.example/profile/{creator}", "avatar": None},
            "created_at": f"2026-10-{1 + n % 28:02d}T12:00:00+00:00", "body": f"<p>{html.escape(caption)}</p>", "summary": caption,
            "tags": tags, "nsfw": False, "media": media, "link": None, "poll": None, "caption_chain": [], "reposted_from": None,
            "is_ask": False, "note_count": {"likes": n * 3, "reposts": n, "comments": 0}, "liked": pid in LIKED,
        }
        posts.append(post)
    # 7004 is city-lights reblogging 7000 by sunny-days: the original's media, credited to the original
    original = next(p for p in posts if p["id"] == 7000)
    reblog = next(p for p in posts if p["id"] == 7004)
    reblog.update(media=original["media"], type=original["type"], profile={**reblog["profile"], "name": "city-lights",
                  "url": "https://imaglr.example/profile/city-lights"}, tags=["reblog"], summary="Had to share this",
                  reposted_from={"id": 7000, "url": original["url"], "profile": original["profile"]})
    return sorted(posts, key=lambda p: p["id"], reverse=True)


def png_bytes(seed, w=240, h=180):
    """A small PNG, different for every seed (so Stash never sees two saves as the same file)."""
    import struct
    import zlib
    r, g, b = (seed * 37) % 256, (seed * 91) % 256, (seed * 53) % 256
    rows = []
    for y in range(h):
        rows.append(b"\x00" + bytes(v for x in range(w) for v in ((r + x) % 256, (g + y) % 256, (b + x + y) % 256)))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))


def media_file(name):
    """The bytes of a catalogue media file, made on first request and kept in the state folder."""
    import shutil
    import subprocess
    match = re.fullmatch(r"(\d+)-(\d+)(-thumb)?\.(png|gif|mp4)", name)
    if not match:
        return None
    folder = os.path.join(STATE, "media")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        seed = int(match.group(1)) * 10 + int(match.group(2))
        ext = match.group(4)
        if ext == "png":
            with open(path + ".tmp", "wb") as f:
                f.write(png_bytes(seed))
        else:
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                return None
            hue = f"hue=h={seed % 360}"
            if ext == "gif":
                args = ["-f", "lavfi", "-i", "testsrc2=s=240x180:r=10:d=1", "-vf", hue, "-f", "gif"]
            else:
                args = ["-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=3", "-f", "lavfi", "-i", f"sine=frequency={200 + seed % 400}:d=3",
                        "-vf", hue, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-f", "mp4"]
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args, path + ".tmp"], check=True)
        os.replace(path + ".tmp", path)
    with open(path, "rb") as f:
        return f.read()


def scenario(key):
    match = re.match(r"pbk_([a-z]+)", key or "")
    return match.group(1) if match else None


def profile_for(name):
    blog = {"blogone": "blog-one", "blogtwo": "blog-two"}.get(name, f"blog-{name}")
    return {
        "name": blog, "url": f"https://imaglr.example/profile/{blog}", "avatar": None, "description": "",
        "nsfw": False, "supporter": name != "premium", "is_private": False, "accepts_asks": False,
        "accepts_submissions": False, "counts": {"followers": 0, "following": 0, "posts": 0},
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "fake-imaglr"

    def log_message(self, fmt, *args):
        sys.stderr.write("fake-imaglr: " + fmt % args + "\n")

    # --- helpers ---
    def reply(self, status, payload=None, errors=None, headers=None):
        body = {"meta": {"status": status, "msg": "OK" if status < 400 else "Error"}}
        if errors:
            body["errors"] = [{"code": code, "detail": detail} for code, detail in errors]
        else:
            body["response"] = payload or {}
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-RateLimit-Limit", "5000")
        self.send_header("X-RateLimit-Remaining", "4999")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def auth(self):
        if not self.headers.get("User-Agent") or self.headers["User-Agent"].startswith("Python-urllib"):
            self.send_response(403)  # imaglr's edge: bare 403, no envelope
            self.end_headers()
            return None
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            self.reply(401, errors=[("not_authenticated", "Missing bearer token.")])
            return None
        name = scenario(header[7:])
        if name is None or name == "invalid":
            self.reply(401, errors=[("invalid_key", "Unknown or expired key.")])
            return None
        if name == "suspended":
            self.reply(403, errors=[("account_suspended", "Suspended account.")])
            return None
        return name

    # --- routes ---
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self.index()
        if self.path.startswith("/files/"):
            return self.file()
        if self.path.startswith("/media/"):
            return self.media()
        name = self.auth()
        if name is None:
            return
        if self.path == "/api/v2/user/info":
            return self.reply(200, {"profile": profile_for(name)})
        if self.path == "/api/v2/user/limits":
            return self.reply(200, {"limits": {
                "requests_per_hour": {"limit": 5000, "remaining": 4999, "resets_in": 3600},
                "writes_per_hour": {"limit": 500, "remaining": 500, "resets_in": 0},
                "posts_per_day": {"limit": 1000, "remaining": 1000, "resets_in": 0},
            }})
        return self.browse()

    def do_POST(self):
        name = self.auth()
        if name is None:
            return
        match = re.fullmatch(r"/api/v2/posts/(\d+)/repost", self.path)
        if match:
            if name == "noscope":
                return self.reply(403, errors=[("insufficient_scope", "This key cannot write.")])
            if not any(p["id"] == int(match.group(1)) for p in catalogue(self.headers.get("Host", "localhost"))):
                return self.reply(404, errors=[("post_not_found", "No such post.")])
            with LOCK:
                REPOSTS.append((profile_for(name)["name"], int(match.group(1))))
            return self.reply(201, {"post": {"id": 90000 + len(REPOSTS), "url": "https://imaglr.example/post/reblog"}})
        if self.path == "/api/v2/drafts":
            return self.create_draft(name)
        match = re.fullmatch(r"/api/v2/drafts/(\d+)/(publish|queue)", self.path)
        if match:
            return self.follow_up(name, match.group(1), match.group(2))
        if self.path == "/api/v2/uploads":
            return self.upload_start()
        match = re.fullmatch(r"/api/v2/uploads/([A-Za-z0-9]+)/complete", self.path)
        if match:
            return self.upload_complete(match.group(1))
        match = re.fullmatch(r"/api/v2/uploads/([A-Za-z0-9]+)/chunks/(\d+)", self.path)
        if match:  # imaglr accepts POST for a chunk too
            return self.upload_chunk(match.group(1), int(match.group(2)))
        self.not_allowed()

    def do_PUT(self):
        if self.auth() is None:
            return
        match = re.fullmatch(r"/api/v2/uploads/([A-Za-z0-9]+)/chunks/(\d+)", self.path)
        if match:
            return self.upload_chunk(match.group(1), int(match.group(2)))
        self.not_allowed()

    def do_DELETE(self):
        if self.auth() is None:
            return
        match = re.fullmatch(r"/api/v2/uploads/([A-Za-z0-9]+)", self.path)
        if match:
            with LOCK:
                UPLOADS.pop(match.group(1), None)
            return self.reply(200, {})
        self.not_allowed()

    do_PATCH = lambda self: (self.auth() is not None) and self.not_allowed()

    # --- chunked uploads ---
    def upload_view(self, upload_id):
        u = UPLOADS[upload_id]
        return {"upload": {"id": upload_id, "filename": u["filename"], "size": u["size"], "status": u["status"],
                           "chunk_size": CHUNK_SIZE, "total_chunks": u["total"],
                           "received_chunks": sorted(u["chunks"])}}

    def upload_start(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        import urllib.parse
        fields = dict(urllib.parse.parse_qsl(raw))
        try:
            size = int(fields.get("size") or 0)
        except ValueError:
            size = 0
        if not fields.get("filename") or size <= 0:
            return self.reply(422, errors=[("invalid_size", "filename and size are required.")])
        with LOCK:
            upload_id = f"u{len(UPLOADS) + 1:04d}"
            UPLOADS[upload_id] = {"filename": fields["filename"], "size": size, "chunks": {}, "status": "uploading",
                                  "total": max(1, -(-size // CHUNK_SIZE))}
        self.reply(201, self.upload_view(upload_id))

    def upload_chunk(self, upload_id, index):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        u = UPLOADS.get(upload_id)
        if u is None:
            return self.reply(404, errors=[("upload_not_found", "Unknown upload.")])
        if index >= u["total"]:
            return self.reply(422, errors=[("invalid_index", "Chunk index out of range.")])
        expected = CHUNK_SIZE if index < u["total"] - 1 else u["size"] - CHUNK_SIZE * (u["total"] - 1)
        if len(raw) != expected:
            return self.reply(422, errors=[("invalid_chunk", f"Chunk {index} should be {expected} bytes, got {len(raw)}.")])
        with LOCK:
            u["chunks"][index] = raw
        self.reply(200, self.upload_view(upload_id))

    def upload_complete(self, upload_id):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        u = UPLOADS.get(upload_id)
        if u is None:
            return self.reply(404, errors=[("upload_not_found", "Unknown upload.")])
        if len(u["chunks"]) != u["total"]:
            return self.reply(422, errors=[("upload_incomplete", f"{len(u['chunks'])} of {u['total']} chunks received.")])
        with LOCK:
            u["status"] = "ready"
        self.reply(200, self.upload_view(upload_id))

    def browse(self):
        """The read routes: lists paged with an opaque cursor and an absolute next link, a profile, a post."""
        import urllib.parse
        host = self.headers.get("Host", "localhost")
        parts = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(parts.query))
        posts = catalogue(host)
        path = parts.path
        match = re.fullmatch(r"/api/v2/posts/(\d+)", path)
        if match:
            post = next((p for p in posts if p["id"] == int(match.group(1))), None)
            return self.reply(200, {"post": post}) if post else self.reply(404, errors=[("post_not_found", "No such post.")])
        match = re.fullmatch(r"/api/v2/profiles/([^/]+)/following", path)
        if match:  # every blog follows three of the made-up creators
            people = [{"name": c, "url": f"https://imaglr.example/profile/{c}", "avatar": None} for c in CREATORS[:3]]
            who = urllib.parse.unquote(match.group(1))
            return self.reply(200, {"profile": {"name": who, "url": f"https://imaglr.example/profile/{who}", "avatar": None},
                                    "following": people})
        match = re.fullmatch(r"/api/v2/profiles/([^/]+)(/posts)?", path)
        if match:
            name = urllib.parse.unquote(match.group(1))
            if name not in CREATORS:
                return self.reply(404, errors=[("profile_not_found", "No such profile.")])
            if not match.group(2):
                return self.reply(200, {"profile": {"name": name, "url": f"https://imaglr.example/profile/{name}", "avatar": None,
                                                    "description": f"Made-up creator {name}", "nsfw": False, "supporter": True,
                                                    "counts": {"followers": 12, "following": 3, "posts": 6}}})
            posts = [p for p in posts if p["profile"]["name"] == name]
        elif path == "/api/v2/user/feed":
            pass
        elif path == "/api/v2/user/likes":
            posts = [p for p in posts if p["id"] in LIKED]
        elif path == "/api/v2/tagged":
            tag = (query.get("tag") or "").casefold()
            if not tag:
                return self.reply(400, errors=[("tag_required", "Which tag?")])
            posts = [p for p in posts if tag in (t.casefold() for t in p["tags"])]
        else:
            return self.not_allowed()
        limit = max(1, min(50, int(query.get("limit") or 20)))
        start = int(query.get("cursor") or 0)
        page = posts[start:start + limit]
        payload = {"posts": page}
        if start + limit < len(posts):
            nxt = urllib.parse.urlencode({**{k: v for k, v in query.items() if k != "cursor"}, "cursor": str(start + limit)})
            payload["_links"] = {"next": {"href": f"http://{host}{path}?{nxt}"}}
        return self.reply(200, payload)

    def media(self):
        data = media_file(self.path[len("/media/"):].split("?", 1)[0])
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        kind = {"png": "image/png", "gif": "image/gif", "mp4": "video/mp4"}[self.path.rsplit(".", 1)[-1]]
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def not_allowed(self):
        sys.stderr.write(f"fake-imaglr: !!! UNEXPECTED ROUTE {self.command} {self.path}\n")
        self.reply(404, errors=[("not_found", f"{self.command} {self.path} is not a route the plugin may call")])

    def create_draft(self, name):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        first = name not in SEEN_FIRST_POST
        SEEN_FIRST_POST.add(name)
        if name == "noscope":
            return self.reply(403, errors=[("insufficient_scope", "Key not permitted to use this route.")])
        if name == "premium":
            return self.reply(403, errors=[("premium_required", "Supporter status required.")])
        if name == "rejected":
            return self.reply(422, errors=[("content_rejected", "Refused by moderation.")])
        if name == "ratelimit" and first:
            return self.reply(429, errors=[("rate_limited", "Too many requests this hour.")], headers={"Retry-After": "2"})
        if name == "toolarge" and first:
            return self.reply(422, errors=[("file_too_large", "Upload over the size limit.")])
        if name == "flaky" and first:
            return self.reply(500, errors=[("server_error", "Fake server error.")])

        message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
            b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + raw
        )
        fields, files, chunked = {"tags[]": []}, [], False
        for part in message.iter_parts():
            field = part.get_param("name", header="content-disposition")
            if part.get_filename():
                files.append((part.get_filename(), part.get_content_type(), part.get_payload(decode=True)))
            elif field == "tags[]":
                fields["tags[]"].append(part.get_content())
            elif field == "uploads[]":  # a completed chunked upload, referenced by id
                u = UPLOADS.get(part.get_content().strip())
                if u is None or u["status"] != "ready":
                    return self.reply(422, errors=[("invalid_uploads", "Unknown or incomplete upload id.")])
                data = b"".join(u["chunks"][i] for i in range(u["total"]))
                files.append((u["filename"], "application/octet-stream", data))
                chunked = True
                with LOCK:
                    UPLOADS.pop(part.get_content().strip(), None)  # consumed
            else:
                fields[field] = part.get_content()
        if not files and not fields.get("body"):
            return self.reply(422, errors=[("post_empty", "Empty post.")])
        if len(files) > 10:
            return self.reply(422, errors=[("invalid_media", "Too many files.")])

        with LOCK:
            draft_id = str(96000000 + len(DRAFTS) + 1)
            folder = os.path.join(STATE, "drafts", draft_id)
            os.makedirs(folder, exist_ok=True)
            for n, (filename, _, content) in enumerate(files, 1):
                with open(os.path.join(folder, f"{n:02d}-{os.path.basename(filename)}"), "wb") as f:
                    f.write(content)
            tags = [t for t in fields["tags[]"] if t != "banned" and not t.startswith("banned-")]
            record = {
                "id": int(draft_id), "blog": profile_for(name)["name"], "state": "draft",
                "body": fields.get("body"), "tags_sent": fields["tags[]"], "tags": tags,
                "files": [{"name": f, "type": t, "bytes": len(c)} for f, t, c in files],
                "chunked": chunked,
            }
            DRAFTS[draft_id] = record
            with open(os.path.join(folder, "draft.json"), "w") as f:
                json.dump(record, f, indent=2)
        self.reply(201, {"post": self.post_object(record)})

    def follow_up(self, name, draft_id, action):
        record = DRAFTS.get(draft_id)
        if record is None or record["blog"] != profile_for(name)["name"]:
            return self.reply(404, errors=[("draft_not_found", "Unknown draft.")])
        if name == "nopublish":
            return self.reply(500, errors=[("server_error", "Fake server error.")])
        record["state"] = {"publish": "published", "queue": "queued"}[action]
        self.reply(200, {"post": self.post_object(record)})

    def post_object(self, record):
        return {
            "id": record["id"], "url": f"https://imaglr.example/post/{record['id']}",
            "type": "image", "tags": record["tags"], "body": record["body"],
            "media": [{"url": None, "kind": "image", "mime": f["type"]} for f in record["files"]],
        }

    # --- viewer ---
    def index(self):
        rows = []
        for draft_id, r in sorted(DRAFTS.items(), reverse=True):
            files = " ".join(
                f'<a href="/files/{draft_id}/{n:02d}-{html.escape(f["name"])}">{html.escape(f["name"])}</a>'
                f' ({f["bytes"] // 1024} KB)'
                for n, f in enumerate(r["files"], 1)
            )
            rows.append(
                f"<tr><td>{draft_id}</td><td>{html.escape(r['blog'])}</td><td>{r['state']}"
                f"{' (chunked)' if r.get('chunked') else ''}</td><td>{files}</td>"
                f"<td>{html.escape(', '.join(r['tags']))}</td><td>{html.escape(r['body'] or '')}</td></tr>"
            )
        page = (
            "<!doctype html><meta charset=utf-8><title>fake imaglr</title>"
            "<style>body{font:14px system-ui;margin:1rem}td,th{border:1px solid #ccc;padding:4px;vertical-align:top}"
            "table{border-collapse:collapse}</style><h1>fake imaglr: received posts</h1><table>"
            "<tr><th>id</th><th>blog</th><th>state</th><th>files</th><th>tags kept</th><th>body</th></tr>"
            + "".join(rows) + "</table><h2>reblogs</h2><ul>"
            + "".join(f"<li>{html.escape(blog)} reblogged post {pid}</li>" for blog, pid in REPOSTS) + "</ul>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def file(self):
        path = os.path.normpath(os.path.join(STATE, "drafts", self.path[len("/files/"):]))
        if not path.startswith(os.path.join(STATE, "drafts")) or not os.path.isfile(path):
            self.send_response(404)
            self.end_headers()
            return
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    os.makedirs(STATE, exist_ok=True)
    print(f"fake imaglr on http://0.0.0.0:{PORT}/api/v2, uploads in {STATE}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

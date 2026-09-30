#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""A fake imaglr API v2 for local testing. Development only; never shipped with the plugin.

Implements the five routes the plugin may call, with the same response envelope shape (error texts are
this fake's own words; the plugin only ever branches on error codes):
GET /user/info, GET /user/limits, POST /drafts, POST /drafts/{id}/publish, POST /drafts/{id}/queue.
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
        self.not_allowed()

    def do_POST(self):
        name = self.auth()
        if name is None:
            return
        if self.path == "/api/v2/drafts":
            return self.create_draft(name)
        match = re.fullmatch(r"/api/v2/drafts/(\d+)/(publish|queue)", self.path)
        if match:
            return self.follow_up(name, match.group(1), match.group(2))
        self.not_allowed()

    do_PATCH = do_PUT = do_DELETE = lambda self: (self.auth() is not None) and self.not_allowed()

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
        fields, files = {"tags[]": []}, []
        for part in message.iter_parts():
            field = part.get_param("name", header="content-disposition")
            if part.get_filename():
                files.append((part.get_filename(), part.get_content_type(), part.get_payload(decode=True)))
            elif field == "tags[]":
                fields["tags[]"].append(part.get_content())
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
                f"<tr><td>{draft_id}</td><td>{html.escape(r['blog'])}</td><td>{r['state']}</td><td>{files}</td>"
                f"<td>{html.escape(', '.join(r['tags']))}</td><td>{html.escape(r['body'] or '')}</td></tr>"
            )
        page = (
            "<!doctype html><meta charset=utf-8><title>fake imaglr</title>"
            "<style>body{font:14px system-ui;margin:1rem}td,th{border:1px solid #ccc;padding:4px;vertical-align:top}"
            "table{border-collapse:collapse}</style><h1>fake imaglr: received posts</h1><table>"
            "<tr><th>id</th><th>blog</th><th>state</th><th>files</th><th>tags kept</th><th>body</th></tr>"
            + "".join(rows) + "</table>"
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

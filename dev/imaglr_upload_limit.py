#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Probe imaglr's real upload limit: POST test videos of rising size to the test blog as drafts and report what
the edge and the API answer. Discards every draft it creates. Standard library plus ffmpeg on PATH.

    python3 dev/imaglr_upload_limit.py                 # 64, 106, 215, 317, 420, 486 MB, stop at the first refusal
    python3 dev/imaglr_upload_limit.py --all           # don't stop at the first refusal
    python3 dev/imaglr_upload_limit.py --mb 95 101     # chosen sizes (MB, decimal)

The key comes from dev/.env.local (IMAGLR_TEST_KEY); never pass it on the command line. Measured 2026-10-08:
anything over 100 MiB per request gets a bare 413 from Cloudflare, whatever imaglr's documentation says.
"""

import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

HOST = "imaglr.com"
UA = "stash-imaglr-upload-limit-probe"
MB_PER_SECOND = 6.07  # of the source below at 48 Mbit/s video + 128 kbit/s audio (decimal MB)


def load_key() -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local")
    try:
        for line in open(path, encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            if k == "IMAGLR_TEST_KEY":
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    sys.exit(f"no IMAGLR_TEST_KEY in {path}")


def make_sources(work: str, sizes_mb: list[float]) -> list[str]:
    """One high-bitrate source, cut by stream copy to roughly each size."""
    longest = max(sizes_mb) / MB_PER_SECOND + 2
    src = os.path.join(work, "source.mp4")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30,noise=alls=40:allf=t",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", f"{longest:.0f}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "48000k", "-minrate", "48000k", "-maxrate", "48000k",
                    "-bufsize", "96000k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", src],
                   check=True)
    out = []
    for mb in sizes_mb:
        path = os.path.join(work, f"cut_{mb:g}mb.mp4")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-t", f"{mb / MB_PER_SECOND:.2f}",
                        "-c", "copy", "-movflags", "+faststart", path], check=True)
        out.append(path)
    return out


def upload(key: str, path: str):
    """POST one file as a draft over a raw TLS socket (so a mid-body close still yields the server's reply)."""
    size = os.path.getsize(path)
    b = "----probe-" + uuid.uuid4().hex
    head = (f"--{b}\r\nContent-Disposition: form-data; name=\"body\"\r\n\r\n<p>upload limit probe (discarded)</p>\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"media[]\"; filename=\"{os.path.basename(path)}\"\r\n"
            f"Content-Type: video/mp4\r\n\r\n").encode()
    tail = f"\r\n--{b}--\r\n".encode()
    total = len(head) + size + len(tail)
    req = (f"POST /api/v2/drafts HTTP/1.1\r\nHost: {HOST}\r\nAuthorization: Bearer {key}\r\nAccept: application/json\r\n"
           f"User-Agent: {UA}\r\nContent-Type: multipart/form-data; boundary={b}\r\nContent-Length: {total}\r\n"
           f"Connection: close\r\n\r\n").encode()
    sock = ssl.create_default_context().wrap_socket(socket.create_connection((HOST, 443), timeout=900), server_hostname=HOST)
    started = time.time()
    sent = 0
    err = None
    try:
        sock.sendall(req + head)
        with open(path, "rb") as f:
            while True:
                chunk = f.read(256 * 1024)
                if not chunk:
                    break
                sock.sendall(chunk)
                sent += len(chunk)
        sock.sendall(tail)
    except OSError as e:
        err = f"{type(e).__name__} after {sent / 1e6:.1f} MB"
    resp = b""
    try:
        sock.settimeout(600)
        while len(resp) < 200000:
            d = sock.recv(65536)
            if not d:
                break
            resp += d
    except OSError as e:
        resp += f"<recv: {type(e).__name__}>".encode()
    sock.close()
    status = resp.split(b"\r\n", 1)[0].decode("latin1").strip() if resp else "<no response>"
    body = resp.split(b"\r\n\r\n", 1)[1].decode("utf-8", "replace") if b"\r\n\r\n" in resp else ""
    draft_id = None
    served_by = "cloudflare" if "cloudflare" in body.lower() and "<html" in body.lower() else "imaglr"
    try:
        d = json.loads(body[body.index("{"):body.rindex("}") + 1])
        draft_id = (d.get("response") or {}).get("draft", {}).get("id")
    except (ValueError, AttributeError):
        pass
    return size, status, err, draft_id, served_by, time.time() - started


def discard(key: str, draft_id) -> str:
    req = urllib.request.Request(f"https://{HOST}/api/v2/drafts/{draft_id}", method="DELETE",
                                 headers={"Authorization": f"Bearer {key}", "Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return f"draft {draft_id} discarded ({r.status})"
    except urllib.error.HTTPError as e:
        return f"draft {draft_id} NOT discarded ({e.code}): delete it on imaglr"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mb", type=float, nargs="+", default=[64, 106, 215, 317, 420, 486], help="sizes to try, decimal MB (approximate: the cuts land on keyframes, so a little over)")
    ap.add_argument("--all", action="store_true", help="keep going after a refusal")
    args = ap.parse_args()
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is not on PATH")
    key = load_key()
    work = tempfile.mkdtemp(prefix="imaglr-limit-")
    try:
        print(f"making {len(args.mb)} test videos…", flush=True)
        paths = make_sources(work, sorted(args.mb))
        print(f"{time.strftime('%Y-%m-%d %H:%M %Z')}: POST /api/v2/drafts, one file per request\n")
        for path in paths:
            size, status, err, draft_id, served_by, dt = upload(key, path)
            print(f"{size / 1e6:6.1f} MB ({size / 1048576:6.1f} MiB) -> {status:<32} {served_by:<10} {dt:4.0f}s"
                  + (f"  send: {err}" if err else ""), flush=True)
            if draft_id:
                print(f"         {discard(key, draft_id)}", flush=True)
            elif not args.all:
                print("         stopping at the first refusal (use --all to continue)")
                break
            time.sleep(3)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# SPDX-License-Identifier: AGPL-3.0-only
"""imaglr client against a local fake server on 127.0.0.1; never the real imaglr."""

from __future__ import annotations

import builtins
import json
import os
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from imaglr_integration.imaglr import client as client_mod
from imaglr_integration.imaglr.client import ImaglrClient, parse_draft_response
from imaglr_integration.imaglr.errors import ErrorClass, ImaglrError, classify, field_from_code


def envelope(response=None, errors=None, status=200):
    body = {"meta": {"status": status, "msg": "ok" if not errors else "error"}}
    if errors is not None:
        body["errors"] = errors
    else:
        body["response"] = response or {}
    return json.dumps(body).encode()


class FakeImaglr:
    """Records each request and answers with the queued (status, body, headers) replies, else an empty envelope."""

    def __init__(self):
        self.requests = []
        self.replies = []
        self.keep_bodies = True
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body, received = bytearray(), 0
                while received < length:
                    chunk = self.rfile.read(min(1 << 20, length - received))
                    if not chunk:
                        break
                    received += len(chunk)
                    if fake.keep_bodies:
                        body += chunk
                fake.requests.append(
                    {"method": self.command, "path": self.path, "headers": self.headers, "body": bytes(body),
                     "received": received}
                )
                status, payload, headers = fake.replies.pop(0) if fake.replies else (200, envelope(), {})
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/v2"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def reply(self, status=200, body=None, headers=None):
        self.replies.append((status, envelope() if body is None else body, headers or {}))

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.server = FakeImaglr()
        self.addCleanup(self.server.close)
        self.client = ImaglrClient("sekret", "1.2.3", self.server.base_url)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as f:
            f.write(data)
        return path


def parse_multipart(req):
    """A recorded request's form parts in order, as [(headers dict, content bytes)]."""
    boundary = req["headers"]["Content-Type"].split("boundary=", 1)[1].encode()
    chunks = req["body"].split(b"--" + boundary)
    assert chunks[0] == b"" and chunks[-1] == b"--\r\n", (chunks[0], chunks[-1])
    parts = []
    for chunk in chunks[1:-1]:
        head, _, content = chunk[2:].partition(b"\r\n\r\n")
        assert content.endswith(b"\r\n")
        headers = dict(line.split(": ", 1) for line in head.decode().split("\r\n"))
        parts.append((headers, content[:-2]))
    return parts


class HeadersTest(ServerTestCase):
    def test_headers_and_user_agent(self):
        self.server.reply(body=envelope({"name": "someone", "unknown_field": 1}))
        self.assertEqual(self.client.user_info(), {"name": "someone", "unknown_field": 1})
        req = self.server.requests[0]
        self.assertEqual((req["method"], req["path"]), ("GET", "/api/v2/user/info"))
        self.assertEqual(req["headers"]["Authorization"], "Bearer sekret")
        self.assertEqual(req["headers"]["User-Agent"], "stash-imaglr-integration/1.2.3")
        self.assertEqual(req["headers"]["Accept"], "application/json")

    def test_user_limits(self):
        self.server.reply(body=envelope({"hourly": {"remaining": 10}}))
        self.assertEqual(self.client.user_limits(), {"hourly": {"remaining": 10}})
        self.assertEqual(self.server.requests[0]["path"], "/api/v2/user/limits")

    def test_missing_response_object_is_empty(self):
        self.server.reply(body=json.dumps({"meta": {"status": 200}}).encode())
        self.assertEqual(self.client.user_info(), {})


class CreateDraftTest(ServerTestCase):
    def test_multipart_shape_with_several_files_in_order(self):
        a = self.write("a.jpg", b"\xff\xd8jpeg")
        b = self.write("b.png", b"\x89PNGpng")
        c = self.write("clip one.mp4", b"\x00" * 1000)
        d = self.write("raw.bin", b"mov")
        post = {"id": 55, "url": "https://imaglr.com/post/55", "tags": ["a", "b"], "type": "image", "new": {}}
        self.server.reply(body=envelope({"post": post}))
        progress = []
        res = self.client.create_draft(
            [a, b, c, (d, "video/quicktime")], ["a", "b", "banned"], "<p>hi – ünïcode</p>", progress.append
        )
        self.assertEqual((res.id, res.url, res.tags), ("55", "https://imaglr.com/post/55", ["a", "b"]))

        req = self.server.requests[0]
        self.assertEqual((req["method"], req["path"]), ("POST", "/api/v2/drafts"))
        self.assertEqual(req["headers"]["User-Agent"], "stash-imaglr-integration/1.2.3")
        self.assertEqual(int(req["headers"]["Content-Length"]), len(req["body"]))
        self.assertIsNone(req["headers"]["Transfer-Encoding"])
        ctype = req["headers"]["Content-Type"]
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        parts = parse_multipart(req)
        self.assertEqual(
            [(h["Content-Disposition"], h.get("Content-Type"), content) for h, content in parts],
            [
                ('form-data; name="body"', None, "<p>hi – ünïcode</p>".encode()),
                ('form-data; name="tags[]"', None, b"a"),
                ('form-data; name="tags[]"', None, b"b"),
                ('form-data; name="tags[]"', None, b"banned"),
                ('form-data; name="media[]"; filename="a.jpg"', "image/jpeg", b"\xff\xd8jpeg"),
                ('form-data; name="media[]"; filename="b.png"', "image/png", b"\x89PNGpng"),
                ('form-data; name="media[]"; filename="clip one.mp4"', "video/mp4", b"\x00" * 1000),
                ('form-data; name="media[]"; filename="raw.bin"', "video/quicktime", b"mov"),
            ],
        )
        self.assertTrue(progress)
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], 1.0)

    def test_omits_body_and_tags_when_blank(self):
        f = self.write("a.webp", b"x" * 10)
        for body_html in (None, ""):
            self.server.reply(body=envelope({"post": {"id": "1"}}))
            self.client.create_draft([f], [], body_html)
            parts = parse_multipart(self.server.requests[-1])
            names = [h["Content-Disposition"] for h, _ in parts]
            self.assertEqual(names, ['form-data; name="media[]"; filename="a.webp"'])
            self.assertEqual(parts[0][0]["Content-Type"], "image/webp")

    @unittest.skipIf(os.name == "nt", "Windows can't create a file with a quote in its name")
    def test_filename_cannot_break_the_header(self):
        f = self.write('we"ird\\name.gif', b"GIF89a")
        self.server.reply(body=envelope({"post": {"id": "1"}}))
        self.client.create_draft([f])
        headers = parse_multipart(self.server.requests[0])[0][0]
        self.assertEqual(headers["Content-Disposition"], 'form-data; name="media[]"; filename="we_ird_name.gif"')

    def test_refuses_partial_file_and_bad_counts(self):
        part = self.write("a.mp4.part", b"x")
        ok = self.write("a.jpg", b"x")
        for media in ([part], [], [ok] * 11):
            with self.assertRaises(ValueError):
                self.client.create_draft(media, [])
        self.assertEqual(self.server.requests, [])

    def test_accepts_ten_files(self):
        f = self.write("a.jpg", b"x")
        self.server.reply(body=envelope({"post": {"id": "1"}}))
        self.client.create_draft([f] * 10)
        self.assertEqual(len(parse_multipart(self.server.requests[0])), 10)

    def test_draft_response_without_post_id_is_an_error(self):
        f = self.write("a.jpg", b"x")
        self.server.reply(body=envelope({"something": 1}))
        with self.assertRaises(ImaglrError) as cm:
            self.client.create_draft([f])
        self.assertEqual(cm.exception.code, "unexpected_response")


class StreamingTest(ServerTestCase):
    SIZE = 24 * 1024 * 1024 + 123

    def test_large_file_is_streamed_in_chunks(self):
        path = os.path.join(self.tmp.name, "big.mp4")
        with open(path, "wb") as f:
            f.truncate(self.SIZE)  # sparse: no disk or memory cost
        reads = []
        real_open = builtins.open

        class SpyFile:
            def __init__(self, f):
                self._f = f

            def read(self, n=-1):
                reads.append(n)
                return self._f.read(n)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self._f.close()

        def spy_open(p, mode="r", *args, **kwargs):
            return SpyFile(real_open(p, mode, *args, **kwargs))

        self.server.keep_bodies = False
        self.server.reply(body=envelope({"post": {"id": "big"}}))
        with mock.patch.object(client_mod, "open", spy_open, create=True):
            res = self.client.create_draft([path], ["t"])
        self.assertEqual(res.id, "big")
        req = self.server.requests[0]
        self.assertEqual(req["received"], int(req["headers"]["Content-Length"]))
        self.assertGreater(req["received"], self.SIZE)
        self.assertTrue(all(0 < n <= client_mod.CHUNK_SIZE for n in reads), reads)
        self.assertGreaterEqual(len(reads), self.SIZE // client_mod.CHUNK_SIZE)

    def test_body_iterates_to_exactly_its_length(self):
        path = self.write("a.mp4", b"y" * (client_mod.CHUNK_SIZE * 2 + 5))
        body = client_mod.MultipartBody([("tags[]", "t")], [(path, "video/mp4")])
        chunks = list(body)
        self.assertEqual(sum(len(c) for c in chunks), body.length)
        self.assertLessEqual(max(len(c) for c in chunks), client_mod.CHUNK_SIZE)
        self.assertEqual(b"".join(chunks), b"".join(body))  # iterable again, e.g. for a retry

    def test_file_that_shrinks_mid_upload_aborts(self):
        path = self.write("a.mp4", b"y" * 100)
        body = client_mod.MultipartBody([], [(path, "video/mp4")])
        with open(path, "wb") as f:
            f.write(b"y" * 10)
        with self.assertRaises(OSError):
            list(body)


class ErrorTest(ServerTestCase):
    def assertImaglrError(self, call, code, klass, status=None):
        with self.assertRaises(ImaglrError) as cm:
            call()
        self.assertEqual(cm.exception.code, code)
        self.assertEqual(cm.exception.klass, klass)
        if status is not None:
            self.assertEqual(cm.exception.http_status, status)
        return cm.exception

    def test_error_envelope_branches_on_code_with_retry_after(self):
        errors = [{"code": "rate_limited", "detail": "slow down please"}]
        self.server.reply(429, envelope(errors=errors, status=429), {"Retry-After": "7"})
        e = self.assertImaglrError(self.client.user_limits, "rate_limited", ErrorClass.RATE_LIMITED, 429)
        self.assertEqual(e.retry_after, 7.0)
        self.assertEqual(e.detail, "slow down please")
        self.assertEqual(str(e), "rate_limited: slow down please")

    def test_invalid_code_names_the_field(self):
        self.server.reply(422, envelope(errors=[{"code": "invalid_tags", "detail": "too many"}], status=422))
        e = self.assertImaglrError(self.client.user_info, "invalid_tags", ErrorClass.INVALID, 422)
        self.assertEqual(e.field, "tags")

    def test_explicit_field_wins(self):
        self.server.reply(422, envelope(errors=[{"code": "invalid_media", "field": "media[2]"}], status=422))
        e = self.assertImaglrError(self.client.user_info, "invalid_media", ErrorClass.INVALID)
        self.assertEqual(e.field, "media[2]")

    def test_error_codes_classify(self):
        for code, status, klass in [
            ("invalid_key", 401, ErrorClass.AUTH),
            ("insufficient_scope", 403, ErrorClass.SCOPE),
            ("premium_required", 403, ErrorClass.PREMIUM),
            ("file_too_large", 422, ErrorClass.TOO_LARGE),
            ("content_rejected", 422, ErrorClass.REJECTED),
            ("daily_post_limit", 429, ErrorClass.RATE_LIMITED),
            ("draft_not_found", 404, ErrorClass.UNKNOWN),
        ]:
            self.server.reply(status, envelope(errors=[{"code": code}], status=status))
            self.assertImaglrError(self.client.user_info, code, klass, status)

    def test_malformed_errors_list(self):
        self.server.reply(400, envelope(errors=["just a string"], status=400))
        e = self.assertImaglrError(self.client.user_info, "unknown", ErrorClass.UNKNOWN, 400)
        self.assertEqual(e.detail, "just a string")

    def test_non_json_5xx_becomes_server_error(self):
        self.server.reply(502, b"bad gateway")
        self.assertImaglrError(self.client.user_info, "server_error", ErrorClass.TRANSIENT, 502)

    def test_bare_403_is_a_clear_auth_error(self):
        for body in (b"", b"<html>Forbidden</html>"):
            self.server.reply(403, body, {"Content-Type": "text/html"})
            e = self.assertImaglrError(self.client.user_info, "not_authenticated", ErrorClass.AUTH, 403)
            self.assertIn("403", e.detail)

    def test_non_json_429_keeps_retry_after(self):
        self.server.reply(429, b"too many", {"Retry-After": "30"})
        e = self.assertImaglrError(self.client.user_info, "rate_limited", ErrorClass.RATE_LIMITED, 429)
        self.assertEqual(e.retry_after, 30.0)

    def test_unusable_retry_after_is_ignored(self):
        for value in ("Wed, 21 Oct 2026 07:28:00 GMT", "-5", "nan", "inf"):
            self.server.reply(429, envelope(errors=[{"code": "rate_limited"}]), {"Retry-After": value})
            e = self.assertImaglrError(self.client.user_info, "rate_limited", ErrorClass.RATE_LIMITED)
            self.assertIsNone(e.retry_after, value)

    def test_non_json_success_is_unknown(self):
        self.server.reply(200, b"<html>ok?</html>")
        self.assertImaglrError(self.client.user_info, "unknown", ErrorClass.UNKNOWN, 200)

    def test_http_error_without_errors_list(self):
        self.server.reply(404, envelope(status=404))
        self.assertImaglrError(self.client.user_info, "unknown", ErrorClass.UNKNOWN, 404)
        self.server.reply(503, envelope(status=503))
        self.assertImaglrError(self.client.user_info, "server_error", ErrorClass.TRANSIENT, 503)

    def test_redirects_are_not_followed(self):
        self.server.reply(302, b"", {"Location": self.server.base_url + "/posts"})
        self.assertImaglrError(self.client.user_info, "unknown", ErrorClass.UNKNOWN, 302)
        self.assertEqual([r["path"] for r in self.server.requests], ["/api/v2/user/info"])

    def test_network_error_is_transient(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        client = ImaglrClient("sekret", "1.2.3", f"http://127.0.0.1:{port}/api/v2", timeout=5)
        e = self.assertImaglrError(client.user_info, "network_error", ErrorClass.TRANSIENT)
        self.assertNotIn("sekret", str(e))


class PublishQueueTest(ServerTestCase):
    def test_publish_draft(self):
        self.server.reply(body=envelope({"post": {"id": 9, "url": "https://imaglr.com/post/9"}}))
        self.assertEqual(self.client.publish_draft(9), {"post": {"id": 9, "url": "https://imaglr.com/post/9"}})
        req = self.server.requests[0]
        self.assertEqual((req["method"], req["path"]), ("POST", "/api/v2/drafts/9/publish"))
        self.assertEqual(req["headers"]["Authorization"], "Bearer sekret")
        self.assertEqual(req["headers"]["User-Agent"], "stash-imaglr-integration/1.2.3")

    def test_queue_draft(self):
        self.client.queue_draft("d42")
        req = self.server.requests[0]
        self.assertEqual((req["method"], req["path"]), ("POST", "/api/v2/drafts/d42/queue"))

    def test_draft_id_cannot_add_path_segments(self):
        self.client.publish_draft("1/../../posts?x=1")
        self.assertEqual(self.server.requests[0]["path"], "/api/v2/drafts/1%2F..%2F..%2Fposts%3Fx%3D1/publish")

    def test_blank_draft_id_is_refused(self):
        for draft_id in ("", "  "):
            with self.assertRaises(ValueError):
                self.client.queue_draft(draft_id)
        self.assertEqual(self.server.requests, [])

    def test_follow_up_errors_are_classified(self):
        self.server.reply(404, envelope(errors=[{"code": "draft_not_found"}], status=404))
        with self.assertRaises(ImaglrError) as cm:
            self.client.publish_draft("gone")
        self.assertEqual((cm.exception.code, cm.exception.http_status), ("draft_not_found", 404))


class ClassifyTest(unittest.TestCase):
    def test_classify(self):
        for code, klass in [
            ("not_authenticated", ErrorClass.AUTH),
            ("invalid_key", ErrorClass.AUTH),
            ("not_an_api_key", ErrorClass.AUTH),
            ("insufficient_scope", ErrorClass.SCOPE),
            ("premium_required", ErrorClass.PREMIUM),
            ("account_suspended", ErrorClass.PREMIUM),
            ("file_too_large", ErrorClass.TOO_LARGE),
            ("content_rejected", ErrorClass.REJECTED),
            ("invalid_tags", ErrorClass.INVALID),
            ("rate_limited", ErrorClass.RATE_LIMITED),
            ("daily_post_limit", ErrorClass.RATE_LIMITED),
            ("server_error", ErrorClass.TRANSIENT),
            ("feed_unavailable", ErrorClass.TRANSIENT),
            ("network_error", ErrorClass.TRANSIENT),
            ("something_new", ErrorClass.UNKNOWN),
        ]:
            with self.subTest(code=code):
                self.assertEqual(classify(code), klass)
        self.assertEqual(ErrorClass.AUTH, "auth")

    def test_field_from_code(self):
        self.assertEqual(field_from_code("invalid_body"), "body")
        self.assertIsNone(field_from_code("invalid_"))
        self.assertIsNone(field_from_code("rate_limited"))

    def test_error_str(self):
        self.assertEqual(str(ImaglrError("server_error")), "server_error")
        self.assertEqual(str(ImaglrError("x", detail="y")), "x: y")

    def test_parse_draft_response_shapes(self):
        tags = [{"name": "x"}, 3, "y"]
        self.assertEqual(parse_draft_response({"post": {"id": 5, "tags": tags}}).tags, ["x", "y"])
        self.assertEqual(parse_draft_response({"id": "7"}).id, "7")
        self.assertIsNone(parse_draft_response({"draft": {"id": "8", "url": None}}).url)
        with self.assertRaises(ImaglrError):
            parse_draft_response({"something": 1})


if __name__ == "__main__":
    unittest.main()


class BareTooLargeTest(unittest.TestCase):
    def test_bare_413_counts_as_too_large(self):
        from imaglr_integration.imaglr.client import _parse
        from imaglr_integration.imaglr.errors import ErrorClass

        with self.assertRaises(ImaglrError) as ctx:
            _parse(413, {}, b"<html>Request Entity Too Large</html>")
        self.assertEqual(ctx.exception.klass, ErrorClass.TOO_LARGE)

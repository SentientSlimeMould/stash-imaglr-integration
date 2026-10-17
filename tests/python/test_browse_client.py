# SPDX-License-Identifier: AGPL-3.0-only
"""The imaglr client's reading, reblogging and media download, against a local fake server; never the real imaglr."""

import json
import os
import tempfile
import unittest
import urllib.parse

from imaglr_integration.imaglr import client as mod
from imaglr_integration.imaglr.client import DisallowedEndpoint, ImaglrClient, MediaRefused, fetch_media
from imaglr_integration.imaglr.errors import ImaglrError
from tests.python.test_imaglr_client import FakeImaglr, envelope


class ReadingTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeImaglr()
        self.addCleanup(self.server.close)
        self.client = ImaglrClient("pbk_key", "9.9", self.server.base_url)

    def test_a_page_and_the_next(self):
        nxt = f"{self.server.base_url}/user/feed?limit=20&cursor=abc%3D"
        self.server.reply(body=envelope({"posts": [{"id": 1}, {"no": "id"}], "_links": {"next": {"href": nxt}}}))
        page = self.client.feed()
        self.assertEqual([p["id"] for p in page.posts], [1])  # a post without an id is dropped
        self.assertEqual(page.next, nxt)
        self.server.reply(body=envelope({"posts": [{"id": 2}]}))
        last = self.client.feed(page.next)
        self.assertIsNone(last.next)
        first, second = self.server.requests
        self.assertEqual(first["path"], "/api/v2/user/feed?limit=20")
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(second["path"]).query), {"limit": ["20"], "cursor": ["abc="]})
        self.assertEqual(first["headers"]["Authorization"], "Bearer pbk_key")
        self.assertEqual(first["headers"]["User-Agent"], "stash-imaglr-integration/9.9")

    def test_tag_creator_and_post_routes(self):
        self.client.tagged("dry humping")
        self.client.profile_posts("some one")
        self.server.reply(body=envelope({"profile": {"name": "x"}}))
        self.assertEqual(self.client.profile("x"), {"name": "x"})
        self.server.reply(body=envelope({"post": {"id": 5}}))
        self.assertEqual(self.client.post("5"), {"id": 5})
        paths = [r["path"] for r in self.server.requests]
        self.assertEqual(paths[0], "/api/v2/tagged?tag=dry+humping&limit=20")
        self.assertEqual(paths[1], "/api/v2/profiles/some%20one/posts?limit=20")
        self.assertEqual(paths[3], "/api/v2/posts/5")

    def test_a_next_link_elsewhere_is_never_followed(self):
        with self.assertRaises(DisallowedEndpoint):
            self.client.likes("https://elsewhere.example/api/v2/user/likes?cursor=x")
        with self.assertRaises(DisallowedEndpoint):
            self.client.likes(f"{self.server.base_url}/user/feed?cursor=x")  # another list
        self.assertEqual(self.server.requests, [])

    def test_reblog(self):
        self.server.reply(201, envelope({"post": {"id": 9}}))
        self.client.repost("123")
        request = self.server.requests[0]
        self.assertEqual((request["method"], request["path"]), ("POST", "/api/v2/posts/123/repost"))
        self.server.reply(403, envelope(errors=[{"code": "insufficient_scope"}]))
        with self.assertRaises(ImaglrError) as caught:
            self.client.repost("123")
        self.assertEqual(caught.exception.code, "insufficient_scope")
        with self.assertRaises(ValueError):
            self.client.repost(" ")


class LikeTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeImaglr()
        self.addCleanup(self.server.close)
        self.client = ImaglrClient("pbk_key", "9.9", self.server.base_url)

    def test_like_toggles_and_reports_what_imaglr_says(self):
        self.server.reply(body=envelope({"liked": True, "likes": 54}))
        self.assertEqual(self.client.like("123"), {"liked": True, "likes": 54})
        request = self.server.requests[0]
        self.assertEqual((request["method"], request["path"]), ("POST", "/api/v2/posts/123/like"))
        self.server.reply(body=envelope({"post": {"liked": False, "note_count": {"likes": 53}}}))
        self.assertEqual(self.client.like("123"), {"liked": False, "likes": 53})  # however imaglr phrases it
        self.server.reply(body=envelope({}))
        self.assertEqual(self.client.like("123"), {"liked": None, "likes": None})
        self.server.reply(403, envelope(errors=[{"code": "insufficient_scope"}]))
        with self.assertRaises(ImaglrError):
            self.client.like("123")


class MediaTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeImaglr()
        self.addCleanup(self.server.close)
        self.server.httpd.handle_error = lambda *a: None  # the client hanging up mid-file is the point of some tests
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.host = self.server.base_url  # the dev allowance: this test server's address
        self.url = self.server.base_url.replace("/api/v2", "/media/a.mp4")

    def test_downloads_without_the_key(self):
        self.server.reply(200, b"x" * 5000, {"Content-Type": "video/mp4"})
        dest = os.path.join(self.dir.name, "a.mp4")
        size, kind = fetch_media(self.url, dest, "9.9", max_bytes=10_000, extra_host=self.host)
        self.assertEqual((size, kind), (5000, "video/mp4"))
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), b"x" * 5000)
        headers = self.server.requests[0]["headers"]
        self.assertIsNone(headers.get("Authorization"))
        self.assertEqual(headers["User-Agent"], "stash-imaglr-integration/9.9")
        self.assertEqual(os.listdir(self.dir.name), ["a.mp4"])  # no part file left

    def test_refuses_other_hosts_too_big_and_redirects(self):
        dest = os.path.join(self.dir.name, "a.mp4")
        with self.assertRaises(MediaRefused):
            fetch_media(self.url, dest, "9.9", max_bytes=10)  # plain http without the dev allowance
        self.assertEqual(self.server.requests, [])
        self.server.reply(200, b"x" * 5000)
        with self.assertRaises(MediaRefused):
            fetch_media(self.url, dest, "9.9", max_bytes=1000, extra_host=self.host)
        self.server.reply(302, b"", {"Location": "https://elsewhere.example/x"})
        with self.assertRaises(ImaglrError):
            fetch_media(self.url, dest, "9.9", max_bytes=1000, extra_host=self.host)
        self.server.reply(404, b"")
        with self.assertRaises(ImaglrError) as caught:
            fetch_media(self.url, dest, "9.9", max_bytes=1000, extra_host=self.host)
        self.assertEqual(caught.exception.code, "not_found")
        self.assertEqual(os.listdir(self.dir.name), [])  # nothing half-written

    def test_cancel_stops_and_cleans_up(self):
        self.server.reply(200, b"x" * (3 * mod.CHUNK_SIZE))
        with self.assertRaises(mod.UploadCancelled):
            fetch_media(self.url, os.path.join(self.dir.name, "a.mp4"), "9.9", max_bytes=10**9, extra_host=self.host,
                        should_cancel=lambda: True)
        self.assertEqual(os.listdir(self.dir.name), [])


if __name__ == "__main__":
    unittest.main()

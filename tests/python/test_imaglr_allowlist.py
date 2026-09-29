# SPDX-License-Identifier: AGPL-3.0-only
"""Allowlist guarantee: the imaglr client can reach exactly five endpoints (spec Amendment 6).

Drafts first, then optionally queue or publish them. Never editing or deleting posts, scheduling, or
changing queue settings.
"""

from __future__ import annotations

import inspect
import os
import re
import unittest

from imaglr_integration.imaglr import client as mod
from imaglr_integration.imaglr.client import ALLOWED_ENDPOINTS, DisallowedEndpoint, ImaglrClient
from tests.python.test_imaglr_client import FakeImaglr

ALLOWED_ROUTES = {"/user/info", "/user/limits", "/drafts", "/drafts/{id}/publish", "/drafts/{id}/queue"}
FORBIDDEN = [
    "/posts", "/schedule", "/settings", "/reorder", "/pages", "/submissions", "/accept", "/delete", "/follow",
    "/like", "/reblog", "/repost", "/blocks", "/draft\"", "/queue/",
]


class AllowlistTest(unittest.TestCase):
    def test_allowlist_is_exactly_five(self):
        self.assertEqual(
            ALLOWED_ENDPOINTS,
            frozenset(
                {
                    ("GET", "/user/info"),
                    ("GET", "/user/limits"),
                    ("POST", "/drafts"),
                    ("POST", "/drafts/{id}/publish"),
                    ("POST", "/drafts/{id}/queue"),
                }
            ),
        )

    def test_source_contains_no_other_route_literals(self):
        src = inspect.getsource(mod)
        routes = set(re.findall(r"[\"'](/[a-z_{}/]+)[\"']", src))
        self.assertLessEqual(routes, ALLOWED_ROUTES)
        for bad in FORBIDDEN:
            self.assertFalse(bad in src, bad)

    def test_single_gateway(self):
        """Only `_request` builds a request, and it checks the allowlist before doing so."""
        src = inspect.getsource(mod)
        gateway = inspect.getsource(ImaglrClient._request)
        self.assertEqual(src.count("Request("), 1)
        self.assertIn("urllib.request.Request(", gateway)
        self.assertEqual(src.count(".open("), 1)
        self.assertIn("self._opener.open(", gateway)
        self.assertLess(gateway.index("ALLOWED_ENDPOINTS"), gateway.index("Request("))
        for other in ("urlopen", "HTTPConnection", "HTTPSConnection", "socket", "subprocess", "curl"):
            self.assertFalse(other in src, other)

    def test_public_methods_are_the_permitted_operations(self):
        public = {n for n, v in vars(ImaglrClient).items() if callable(v) and not n.startswith("_")}
        self.assertEqual(public, {"user_info", "user_limits", "create_draft", "publish_draft", "queue_draft"})

    def test_only_client_module_knows_the_api_url(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(mod.__file__)))
        offenders = []
        for folder, _, names in os.walk(root):
            for name in names:
                path = os.path.join(folder, name)
                if name.endswith(".py") and os.path.abspath(path) != os.path.abspath(mod.__file__):
                    with open(path, encoding="utf-8") as f:
                        if "imaglr.com/api" in f.read():
                            offenders.append(path)
        self.assertEqual(offenders, [])


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeImaglr()
        self.addCleanup(self.server.close)
        self.client = ImaglrClient("k", "1.0", self.server.base_url)

    def test_request_rejects_everything_else(self):
        for method, path in [
            ("POST", "/posts"),
            ("POST", "/drafts/1/publish"),  # a concrete path is not a permitted route template
            ("POST", "/drafts/1/queue"),
            ("GET", "/drafts"),
            ("PUT", "/drafts"),
            ("PATCH", "/drafts/{id}"),
            ("DELETE", "/drafts/{id}"),
            ("DELETE", "/drafts"),
            ("GET", "/queue"),
            ("POST", "/queue/{id}/publish"),
            ("POST", "/queue/{id}/schedule"),
            ("PUT", "/queue/settings"),
            ("GET", "/drafts/{id}/publish"),
            ("POST", "/user/info"),
            ("POST", "/drafts/"),
            ("POST", "/drafts?x=1"),
            ("POST", "/submissions/{id}/accept"),
        ]:
            with self.subTest(method=method, path=path):
                with self.assertRaises(DisallowedEndpoint):
                    self.client._request(method, path, {"id": "1"})
        self.assertEqual(self.server.requests, [])

    def test_method_is_case_insensitive_for_permitted_routes(self):
        self.client._request("get", "/user/info")
        self.assertEqual(self.server.requests[0]["method"], "GET")


if __name__ == "__main__":
    unittest.main()

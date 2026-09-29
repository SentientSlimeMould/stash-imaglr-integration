# SPDX-License-Identifier: AGPL-3.0-only
import unittest

from imaglr_integration.stash import StashClient, base_url


class BaseUrlTest(unittest.TestCase):
    def test_wildcard_hosts_map_to_loopback(self):
        for host in ("0.0.0.0", "::", "", None):
            self.assertEqual(base_url({"Scheme": "http", "Host": host, "Port": 9999}), "http://127.0.0.1:9999")

    def test_specific_hosts_are_kept(self):
        self.assertEqual(base_url({"Scheme": "https", "Host": "stash.lan", "Port": 443}), "https://stash.lan:443")
        self.assertEqual(base_url({"Scheme": "http", "Host": "192.0.2.5", "Port": 6969}), "http://192.0.2.5:6969")

    def test_ipv6_hosts_are_bracketed(self):
        self.assertEqual(base_url({"Scheme": "http", "Host": "::1", "Port": 9999}), "http://[::1]:9999")

    def test_defaults(self):
        self.assertEqual(base_url({}), "http://127.0.0.1:9999")


class CookieTest(unittest.TestCase):
    def test_session_cookie_is_refreshed_from_set_cookie(self):
        client = StashClient({"SessionCookie": {"Name": "session", "Value": "old"}})
        client._refresh_cookie(["other=1; Path=/", "session=new; Path=/; HttpOnly"])
        self.assertEqual(client._cookie_value, "new")

    def test_missing_cookie_is_allowed(self):
        client = StashClient({"SessionCookie": None})
        self.assertIsNone(client._cookie_value)


if __name__ == "__main__":
    unittest.main()

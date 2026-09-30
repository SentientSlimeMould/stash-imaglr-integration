# SPDX-License-Identifier: AGPL-3.0-only
"""GraphQL client for talking back to the Stash that started the plugin.

Works with every Stash auth setup (docs/stash-plugin-facts.md §4): it sends the session cookie Stash
passes in server_connection, keeps it refreshed from Set-Cookie, and switches to Stash's API key when
one exists, so tasks outlive the cookie's one-hour lifetime.
"""

import ipaddress
import json
import ssl
import urllib.error
import urllib.request

from .. import log

_WILDCARD_HOSTS = {"", "0.0.0.0", "::", "[::]"}


class StashError(Exception):
    pass


def base_url(connection):
    scheme = connection.get("Scheme") or "http"
    host = str(connection.get("Host") or "")
    if host in _WILDCARD_HOSTS:
        host = "127.0.0.1"
    try:
        if ipaddress.ip_address(host.strip("[]")).version == 6:
            host = f"[{host.strip('[]')}]"
    except ValueError:
        pass  # a hostname
    return f"{scheme}://{host}:{connection.get('Port') or 9999}"


def _is_loopback(url):
    host = urllib.request.urlparse(url).hostname or ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


class StashClient:
    def __init__(self, connection, timeout=60):
        self.url = base_url(connection)
        self.timeout = timeout
        cookie = connection.get("SessionCookie") or {}
        self._cookie_name = cookie.get("Name") or "session"
        self._cookie_value = cookie.get("Value")
        log.register_secret(self._cookie_value)
        self._api_key = None
        self._api_key_checked = False
        # Stash's own certificate on loopback is typically self-signed; elsewhere verify normally.
        self._ssl = ssl._create_unverified_context() if _is_loopback(self.url) else None

    def gql(self, query, variables=None):
        self._check_api_key()
        return self._request(query, variables)

    def auth_headers(self):
        """Headers that authenticate a plain HTTP request to Stash (a download, ffmpeg's HTTP input)
        the same way gql() does: Stash's API key when one exists, else the session cookie."""
        self._check_api_key()
        if self._api_key:
            return {"ApiKey": self._api_key}
        if self._cookie_value:
            return {"Cookie": f"{self._cookie_name}={self._cookie_value}"}
        return {}

    @property
    def ssl_context(self):
        return self._ssl

    def _check_api_key(self):
        if not self._api_key_checked:
            self._api_key_checked = True
            key = self._request("{ configuration { general { apiKey } } }", None)
            self._api_key = key["configuration"]["general"]["apiKey"] or None
            log.register_secret(self._api_key)

    def _request(self, query, variables):
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        req = urllib.request.Request(self.url + "/graphql", body, {"Content-Type": "application/json"})
        if self._api_key:
            req.add_header("ApiKey", self._api_key)
        elif self._cookie_value:
            req.add_header("Cookie", f"{self._cookie_name}={self._cookie_value}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl) as resp:
                self._refresh_cookie(resp.headers.get_all("Set-Cookie") or [])
                result = json.load(resp)
        except urllib.error.HTTPError as e:
            raise StashError(f"Stash returned HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise StashError(f"Cannot reach Stash at {self.url}: {e.reason}") from None
        if result.get("errors"):
            raise StashError("; ".join(err.get("message", "?") for err in result["errors"]))
        return result["data"]

    def _refresh_cookie(self, headers):
        for header in headers:
            name, _, rest = header.partition("=")
            if name.strip() == self._cookie_name:
                self._cookie_value = rest.split(";", 1)[0]
                log.register_secret(self._cookie_value)

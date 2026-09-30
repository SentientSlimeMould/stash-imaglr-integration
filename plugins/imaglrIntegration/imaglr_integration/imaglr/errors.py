# SPDX-License-Identifier: AGPL-3.0-only
"""imaglr error model and classification. Branch on `code`, never on `detail`."""

from __future__ import annotations

from enum import Enum


class ErrorClass(str, Enum):
    AUTH = "auth"
    SCOPE = "scope"
    PREMIUM = "premium"  # account-level block: premium lapsed or account suspended; sending pauses
    TOO_LARGE = "too_large"
    REJECTED = "rejected"
    INVALID = "invalid"
    RATE_LIMITED = "rate_limited"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


AUTH_CODES = {"not_authenticated", "invalid_key", "not_an_api_key"}
TRANSIENT_CODES = {"server_error", "feed_unavailable", "network_error"}


class ImaglrError(Exception):
    def __init__(
        self,
        code: str,
        detail: str = "",
        http_status: int | None = None,
        retry_after: float | None = None,
        field: str | None = None,
    ):
        super().__init__(code, detail)
        self.code = code
        self.detail = detail
        self.body_sent = False  # network_error after the whole request body went out (the server may have acted)
        self.http_status = http_status
        self.retry_after = retry_after
        self.field = field

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}" if self.detail else self.code

    @property
    def klass(self) -> ErrorClass:
        return classify(self.code)


def classify(code: str) -> ErrorClass:
    if code in AUTH_CODES:
        return ErrorClass.AUTH
    if code == "insufficient_scope":
        return ErrorClass.SCOPE
    if code in ("premium_required", "account_suspended"):
        return ErrorClass.PREMIUM
    if code == "file_too_large":
        return ErrorClass.TOO_LARGE
    if code == "content_rejected":
        return ErrorClass.REJECTED
    if code.startswith("invalid_"):
        return ErrorClass.INVALID
    if code in ("rate_limited", "daily_post_limit"):
        return ErrorClass.RATE_LIMITED
    if code in TRANSIENT_CODES:
        return ErrorClass.TRANSIENT
    return ErrorClass.UNKNOWN


def field_from_code(code: str) -> str | None:
    if code.startswith("invalid_") and len(code) > len("invalid_"):
        return code[len("invalid_") :]
    return None

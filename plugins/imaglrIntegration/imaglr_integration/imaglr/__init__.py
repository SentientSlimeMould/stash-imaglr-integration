# SPDX-License-Identifier: AGPL-3.0-only
"""Talking to imaglr: the allowlisted API client and its error model."""

from .client import ALLOWED_ENDPOINTS, DisallowedEndpoint, DraftResult, ImaglrClient
from .errors import ErrorClass, ImaglrError, classify

__all__ = [
    "ALLOWED_ENDPOINTS",
    "DisallowedEndpoint",
    "DraftResult",
    "ErrorClass",
    "ImaglrClient",
    "ImaglrError",
    "classify",
]

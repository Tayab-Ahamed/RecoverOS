"""Razorpay webhook signature verification.

The signature is an HMAC-SHA256 hex digest over the RAW request body. Parsing
the JSON and re-serialising it before verifying will produce a different byte
sequence and fail intermittently, which is risk R5. The function therefore
accepts bytes and refuses str.
"""

from __future__ import annotations

import hashlib
import hmac


class SignatureError(Exception):
    pass


def compute_signature(raw_body: bytes, secret: str) -> str:
    if not isinstance(raw_body, bytes):
        raise SignatureError(
            "raw_body must be bytes; re-serialised JSON will not match the digest"
        )
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def verify_signature(raw_body: bytes, header_signature: str, secret: str) -> bool:
    """Constant-time comparison of the expected and supplied digests."""
    if not header_signature:
        return False
    expected = compute_signature(raw_body, secret)
    return hmac.compare_digest(expected, header_signature)

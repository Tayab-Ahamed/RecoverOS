"""Small, dependency-free JWT verification for the production API boundary."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: frozenset[str]


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_bearer(request: Request, secret: str) -> Principal:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Bearer authentication required")
    token = header[7:].strip().split(".")
    if len(token) != 3:
        raise HTTPException(401, "invalid bearer token")
    try:
        encoded_header, encoded_payload, encoded_signature = token
        header_obj = json.loads(_decode(encoded_header))
        payload = json.loads(_decode(encoded_payload))
        if header_obj.get("alg") != "HS256":
            raise ValueError("unsupported algorithm")
        expected = hmac.new(
            secret.encode(),
            f"{encoded_header}.{encoded_payload}".encode(),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected, _decode(encoded_signature)):
            raise ValueError("bad signature")
        subject = str(payload["sub"])
        roles = frozenset(str(role) for role in payload.get("roles", []))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(401, "invalid bearer token") from exc
    return Principal(subject=subject, roles=roles)

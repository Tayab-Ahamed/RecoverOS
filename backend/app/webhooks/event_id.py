"""Provider event identity.

Replay protection is only as strong as the identifier it keys on. Two rules
follow from that, and both are enforced here rather than at the HTTP edge so
they can be tested without a web server:

1. The identifier must be **durable across processes**. `hash()` is not: Python
   randomises string and bytes hashing per interpreter invocation unless
   PYTHONHASHSEED is fixed, so a restart would let an already-processed event
   through a second time. A SHA-256 digest of the raw body is stable forever.

2. In production, a provider event with no event id is **malformed**, not
   something to paper over. Manufacturing an identifier means the deduplication
   key is derived from content the sender controls, so two genuinely distinct
   events with identical bodies would collapse into one, and a single event
   redelivered with a byte-level difference would be processed twice. Neither
   is acceptable when the consequence is marking money as recovered.

The derived form therefore exists only for local development and for the
signed mock replay path, and it must be requested explicitly.

See docs/IMPLEMENTATION_DECISIONS.md, D11.
"""

from __future__ import annotations

import hashlib

from app.domain.errors import MissingProviderEventId

DERIVED_PREFIX = "body:sha256:"


def derive_event_id(raw_body: bytes) -> str:
    """Content-addressed identifier for a request body.

    Deterministic across processes, machines and interpreter versions, which is
    the entire point.
    """
    if not isinstance(raw_body, bytes):
        raise TypeError(
            "raw_body must be bytes; encoding a str here would change the digest"
        )
    return f"{DERIVED_PREFIX}{hashlib.sha256(raw_body).hexdigest()}"


def is_derived(event_id: str) -> bool:
    """True if this identifier was manufactured rather than supplied by the
    provider. Audit consumers use this to tell the two apart."""
    return event_id.startswith(DERIVED_PREFIX)


def resolve_event_id(
    header_event_id: str | None,
    raw_body: bytes,
    *,
    allow_derived: bool = False,
) -> str:
    """Return the identifier to use for replay protection.

    A provider-supplied id always wins. Whitespace-only headers count as
    absent, because a blank header is a missing header.

    Raises MissingProviderEventId when no id was supplied and deriving one is
    not permitted.
    """
    supplied = (header_event_id or "").strip()
    if supplied:
        return supplied

    if not allow_derived:
        raise MissingProviderEventId(
            "provider event id header is absent; refusing to manufacture a "
            "deduplication key for a payment event"
        )

    return derive_event_id(raw_body)

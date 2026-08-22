"""Idempotency and replay protection.

Providers retry webhooks. Processing `payment_link.paid` twice would double
count recovered revenue, so every event is recorded by its provider event id
and the second delivery is a no-op.
"""

from __future__ import annotations

from typing import Protocol


class IdempotencyStore(Protocol):
    def claim(self, key: str) -> bool: ...
    def remember(self, key: str) -> None: ...

    def seen(self, key: str) -> bool: ...


class InMemoryIdempotencyStore:
    """Used in tests, benchmarks and the offline demo. Redis backs production."""

    def __init__(self) -> None:
        self._keys: set[str] = set()

    def seen(self, key: str) -> bool:
        return key in self._keys

    def claim(self, key: str) -> bool:
        """Atomically claim an event in the single-process implementation."""
        if key in self._keys:
            return False
        self._keys.add(key)
        return True

    def remember(self, key: str) -> None:
        self._keys.add(key)

    def __len__(self) -> int:
        return len(self._keys)


class RedisIdempotencyStore:
    """Durable, atomic replay protection for deployed workers.

    `SET NX` makes claiming an event one atomic operation. The handler can
    therefore never process the same provider event concurrently in two
    workers, which a `seen()` followed by `remember()` sequence could allow.
    """

    def __init__(self, url: str, ttl_seconds: int = 60 * 60 * 24 * 30) -> None:
        if not url:
            raise ValueError("Redis URL is required")
        import redis

        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._ttl_seconds = ttl_seconds

    def seen(self, key: str) -> bool:
        return bool(self._client.exists(self._key(key)))

    def claim(self, key: str) -> bool:
        return bool(
            self._client.set(
                self._key(key), "1", nx=True, ex=self._ttl_seconds
            )
        )

    def remember(self, key: str) -> None:
        # Kept for protocol compatibility and for rejected/unknown events.
        self._client.set(self._key(key), "1", nx=True, ex=self._ttl_seconds)

    @staticmethod
    def _key(event_id: str) -> str:
        return f"recoveros:webhook:{event_id}"


class SqlIdempotencyStore:
    """Database-backed replay protection for the SQL API path."""

    def __init__(self, session) -> None:
        self.session = session

    def seen(self, key: str) -> bool:
        from sqlalchemy import select
        from app.models.sql import WebhookEvent

        return self.session.scalar(
            select(WebhookEvent.id).where(WebhookEvent.external_event_id == key)
        ) is not None

    def claim(self, key: str) -> bool:
        from sqlalchemy.exc import IntegrityError
        from app.models.sql import WebhookEvent
        from app.domain.entities import new_id

        if self.seen(key):
            return False
        try:
            with self.session.begin_nested():
                self.session.add(WebhookEvent(
                    id=new_id("wh"), external_event_id=key, event_type="unknown",
                    signature_valid=True, processed=False, case_id=None,
                ))
                self.session.flush()
            return True
        except IntegrityError:
            return False

    def remember(self, key: str) -> None:
        # claim() records the event before verification. This method is kept
        # for the shared protocol and is intentionally idempotent.
        self.claim(key)

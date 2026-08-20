"""Idempotency and replay protection.

Providers retry webhooks. Processing `payment_link.paid` twice would double
count recovered revenue, so every event is recorded by its provider event id
and the second delivery is a no-op.
"""

from __future__ import annotations

from typing import Protocol


class IdempotencyStore(Protocol):
    def seen(self, key: str) -> bool: ...
    def remember(self, key: str) -> None: ...


class InMemoryIdempotencyStore:
    """Used in tests, benchmarks and the offline demo. Redis backs production."""

    def __init__(self) -> None:
        self._keys: set[str] = set()

    def seen(self, key: str) -> bool:
        return key in self._keys

    def remember(self, key: str) -> None:
        self._keys.add(key)

    def __len__(self) -> int:
        return len(self._keys)

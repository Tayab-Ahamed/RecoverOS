from __future__ import annotations

import unittest

from app.integrations.idempotency import InMemoryIdempotencyStore


class IdempotencyTests(unittest.TestCase):
    def test_claim_is_atomic_from_the_store_contract(self) -> None:
        store = InMemoryIdempotencyStore()
        self.assertTrue(store.claim("evt_1"))
        self.assertFalse(store.claim("evt_1"))
        self.assertTrue(store.seen("evt_1"))


if __name__ == "__main__":
    unittest.main()

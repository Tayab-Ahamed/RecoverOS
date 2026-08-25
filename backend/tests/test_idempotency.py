"""Idempotency store tests.

Covers the in-memory store contract plus end-to-end webhook replay protection.
These tests catch bugs that only appear on the second delivery of the same
event — bugs that are invisible in a test suite that delivers each event once.
"""
from __future__ import annotations

import json
import unittest

from app.domain.states import CaseState
from app.integrations.idempotency import InMemoryIdempotencyStore
from app.integrations.signature import compute_signature
from tests import factories as f


class TestInMemoryIdempotencyStore(unittest.TestCase):

    def test_first_claim_succeeds(self):
        store = InMemoryIdempotencyStore()
        self.assertTrue(store.claim("evt_1"))

    def test_second_claim_rejected(self):
        store = InMemoryIdempotencyStore()
        store.claim("evt_1")
        self.assertFalse(store.claim("evt_1"))

    def test_seen_reflects_claim(self):
        store = InMemoryIdempotencyStore()
        self.assertFalse(store.seen("evt_x"))
        store.claim("evt_x")
        self.assertTrue(store.seen("evt_x"))

    def test_different_event_ids_are_independent(self):
        store = InMemoryIdempotencyStore()
        self.assertTrue(store.claim("evt_a"))
        self.assertTrue(store.claim("evt_b"))
        # Second claim on 'a' still rejected even though 'b' succeeded
        self.assertFalse(store.claim("evt_a"))

    def test_many_claims_only_first_wins(self):
        store = InMemoryIdempotencyStore()
        results = [store.claim("evt_z") for _ in range(5)]
        self.assertEqual(results, [True, False, False, False, False])


class TestWebhookIdempotency(unittest.TestCase):
    """End-to-end: the same provider event delivered twice must not advance
    the case state twice or record two evidence rows."""

    def _make_paid_body(self, case_id: str, link_id: str = "plink_1") -> bytes:
        return json.dumps({
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {
                    "entity": {
                        "id": link_id,
                        "reference_id": case_id,
                        "amount": 849900,
                        "status": "paid",
                    }
                },
                "payment": {
                    "entity": {
                        "id": "pay_1",
                        "amount": 849900,
                        "status": "captured",
                    }
                },
            },
        }).encode()

    def setUp(self):
        self.sys = f.System()
        self.c = self.sys.register(f.case())
        self.c.state = CaseState.AWAITING_PAYMENT

    def test_same_event_twice_case_advances_once(self):
        """Delivering the same event id twice must not transition the case twice."""
        body = self._make_paid_body(self.c.id)
        sig = compute_signature(body, f.SECRET)

        r1 = self.sys.handler.handle(body, sig, "evt_unique_1")
        r2 = self.sys.handler.handle(body, sig, "evt_unique_1")  # replay

        self.assertTrue(r1.accepted)
        self.assertFalse(r2.accepted)
        # Case should be RECOVERED from the first delivery only
        self.assertEqual(self.c.state, CaseState.RECOVERED)

    def test_duplicate_event_reason_is_replay(self):
        """The second delivery should report why it was rejected."""
        body = self._make_paid_body(self.c.id)
        sig = compute_signature(body, f.SECRET)

        self.sys.handler.handle(body, sig, "evt_replay_test")
        r2 = self.sys.handler.handle(body, sig, "evt_replay_test")

        self.assertFalse(r2.accepted)
        self.assertTrue(
            "replay" in r2.reason.lower() or "duplicate" in r2.reason.lower(),
            f"Expected replay/duplicate reason, got: {r2.reason!r}",
        )

    def test_different_event_ids_both_accepted_at_signature_level(self):
        """Two distinct event IDs: the first advances the case to RECOVERED.
        The second delivery raises InvariantViolation (correct safety behaviour —
        the verifier refuses to process a capture event on a RECOVERED case)."""
        from app.domain.errors import InvariantViolation

        body = self._make_paid_body(self.c.id)
        sig = compute_signature(body, f.SECRET)

        r1 = self.sys.handler.handle(body, sig, "evt_distinct_a")
        self.assertTrue(r1.accepted)
        self.assertEqual(self.c.state, CaseState.RECOVERED)
        # The verifier raises InvariantViolation on a second capture for RECOVERED case.
        # This IS the intended behaviour — no double-recovery possible.
        with self.assertRaises(InvariantViolation):
            self.sys.handler.handle(body, sig, "evt_distinct_b")
        # Evidence is still the first payment only.
        self.assertIsNotNone(self.c.evidence)
        self.assertEqual(self.c.evidence.external_payment_id, "pay_1")


if __name__ == "__main__":
    unittest.main()

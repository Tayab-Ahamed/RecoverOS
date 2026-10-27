import json
import unittest

from app.domain.states import CaseState
from app.integrations.signature import compute_signature
from tests import factories as f


class TestMalformedWebhookPayload(unittest.TestCase):
    def setUp(self):
        self.system = f.System()
        self.case = self.system.register(f.case())
        self.case.state = CaseState.AWAITING_PAYMENT

    def handle(self, body, event_id):
        raw = json.dumps(body).encode()
        return self.system.handler.handle(raw, compute_signature(raw, f.SECRET), event_id)

    def test_nonobject_and_malformed_nested_payloads_are_rejected(self):
        bodies = [
            [], None, 42,
            {"event": ["payment.captured"]},
            {"event": "payment.captured", "payload": []},
            {"event": "payment.captured", "payload": {"payment": "invalid"}},
            {"event": "payment.captured", "payload": {"payment": {"entity": []}}},
            {"event": "payment.captured", "payload": {"payment": {"entity": {"notes": []}}}},
        ]
        for index, body in enumerate(bodies):
            with self.subTest(body=body):
                result = self.handle(body, f"malformed_{index}")
                self.assertFalse(result.accepted)
                self.assertEqual(self.case.state, CaseState.AWAITING_PAYMENT)
                self.assertIsNone(self.case.evidence)
                self.assertEqual(self.system.outcomes, [])

    def test_invalid_amounts_cannot_become_capture_evidence(self):
        for index, amount in enumerate([-1, True, "100", 1.5]):
            with self.subTest(amount=amount):
                body = {"event": "payment.captured", "payload": {"payment": {"entity": {
                    "id": "pay_test", "status": "captured", "amount": amount,
                    "notes": {"reference_id": self.case.id},
                }}}}
                result = self.handle(body, f"bad_amount_{index}")
                self.assertFalse(result.accepted)
                self.assertEqual(self.case.state, CaseState.AWAITING_PAYMENT)
                self.assertIsNone(self.case.evidence)
                self.assertEqual(self.system.outcomes, [])

import json
import unittest

from app.domain.states import CaseState
from app.integrations.signature import compute_signature, verify_signature
from tests import factories as f


class TestSignature(unittest.TestCase):
    def test_roundtrip(self):
        body = b'{"event":"payment_link.paid"}'
        self.assertTrue(verify_signature(body, compute_signature(body, "s"), "s"))

    def test_wrong_secret_fails(self):
        body = b'{"event":"x"}'
        self.assertFalse(verify_signature(body, compute_signature(body, "a"), "b"))

    def test_tampered_body_fails(self):
        sig = compute_signature(b'{"amount":100}', "s")
        self.assertFalse(verify_signature(b'{"amount":999}', sig, "s"))

    def test_missing_signature_fails(self):
        self.assertFalse(verify_signature(b"{}", "", "s"))

    def test_str_body_is_refused(self):
        # Risk R5: re-serialised JSON produces different bytes and would fail
        # intermittently, which is far worse than failing immediately.
        from app.integrations.signature import SignatureError

        with self.assertRaises(SignatureError):
            compute_signature('{"a":1}', "s")


class TestWebhookHandler(unittest.TestCase):
    def setUp(self):
        self.sys = f.System()
        self.case = self.sys.register(f.case())
        self.case.state = CaseState.AWAITING_PAYMENT
        self.body = json.dumps(
            {
                "event": "payment_link.paid",
                "payload": {
                    "payment_link": {
                        "entity": {
                            "id": "plink_1",
                            "reference_id": self.case.id,
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
            }
        ).encode()
        self.sig = compute_signature(self.body, f.SECRET)

    def test_valid_event_is_processed(self):
        r = self.sys.handler.handle(self.body, self.sig, "evt_1")
        self.assertTrue(r.accepted)
        self.assertEqual(self.case.state, CaseState.RECOVERED)

    def test_bad_signature_never_reaches_domain_logic(self):
        r = self.sys.handler.handle(self.body, "deadbeef", "evt_1")
        self.assertFalse(r.accepted)
        self.assertEqual(r.reason, "invalid signature")
        self.assertEqual(self.case.state, CaseState.AWAITING_PAYMENT)

    def test_replay_is_ignored_and_does_not_double_count(self):
        first = self.sys.handler.handle(self.body, self.sig, "evt_1")
        second = self.sys.handler.handle(self.body, self.sig, "evt_1")
        self.assertTrue(first.accepted)
        self.assertFalse(second.accepted)
        self.assertEqual(second.reason, "duplicate event ignored")
        self.assertEqual(self.case.recovered_amount.paise, 849900)

    def test_unknown_case_is_rejected_safely(self):
        body = self.body.replace(self.case.id.encode(), b"case_does_not_exist")
        r = self.sys.handler.handle(body, compute_signature(body, f.SECRET), "evt_9")
        self.assertFalse(r.accepted)
        self.assertEqual(r.reason, "unknown case")

    def test_unparseable_body_is_rejected(self):
        body = b"not json"
        r = self.sys.handler.handle(body, compute_signature(body, f.SECRET), "evt_10")
        self.assertFalse(r.accepted)
        self.assertIn("unparseable", r.reason)

    def test_failed_payment_notes_linkage(self):
        # This linkage is the UNVERIFIED assumption noted in the spec: a failed
        # attempt arrives as a payment event, so association travels in notes.
        body = json.dumps(
            {
                "event": "payment.failed",
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_2",
                            "amount": 849900,
                            "status": "failed",
                            "notes": {"reference_id": self.case.id},
                        }
                    }
                },
            }
        ).encode()
        r = self.sys.handler.handle(body, compute_signature(body, f.SECRET), "evt_11")
        self.assertTrue(r.accepted)
        self.assertEqual(self.case.state, CaseState.FAILED)

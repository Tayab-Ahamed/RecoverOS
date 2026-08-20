import unittest

from app.domain.errors import UnauthorizedActor
from app.domain.states import Actor, CaseState
from tests import factories as f


class TestOutcomeVerifier(unittest.TestCase):
    """Invariant 1: recovery requires verified captured payment evidence."""

    def setUp(self):
        self.sys = f.System()

    def _awaiting(self):
        c = f.case()
        c.state = CaseState.AWAITING_PAYMENT
        return c

    def test_captured_payment_marks_recovered(self):
        c = self._awaiting()
        self.sys.verifier.verify(
            c, "payment_link.paid", "evt_1", "pay_1", 849900, captured=True
        )
        self.assertEqual(c.state, CaseState.RECOVERED)
        self.assertIsNotNone(c.evidence)
        self.assertEqual(c.recovered_amount.paise, 849900)

    def test_authorized_but_uncaptured_is_not_a_recovery(self):
        # Conflating authorized with captured is the easiest way to report a
        # recovery number that is not real.
        c = self._awaiting()
        self.sys.verifier.verify(
            c, "payment.authorized", "evt_2", "pay_2", 849900, captured=False
        )
        self.assertEqual(c.state, CaseState.AWAITING_PAYMENT)
        self.assertIsNone(c.evidence)
        self.assertIsNone(c.recovered_amount)

    def test_paid_event_without_capture_flag_is_refused(self):
        c = self._awaiting()
        self.sys.verifier.verify(
            c, "payment_link.paid", "evt_3", "pay_3", 849900, captured=False
        )
        self.assertEqual(c.state, CaseState.AWAITING_PAYMENT)

    def test_failure_event_moves_to_failed(self):
        c = self._awaiting()
        self.sys.verifier.verify(c, "payment.failed", "evt_4", "pay_4", 849900, False)
        self.assertEqual(c.state, CaseState.FAILED)

    def test_no_other_actor_can_write_recovered(self):
        c = self._awaiting()
        for actor in (Actor.EXECUTOR, Actor.STRATEGIST_AGENT, Actor.SYSTEM, Actor.HUMAN):
            with self.assertRaises(UnauthorizedActor):
                self.sys.sm.transition(c, CaseState.RECOVERED, actor)
        self.assertEqual(c.state, CaseState.AWAITING_PAYMENT)

    def test_recovered_amount_comes_from_evidence_not_from_the_case(self):
        # A partial payment must be recorded as what was actually captured.
        c = self._awaiting()
        self.sys.verifier.verify(
            c, "payment_link.paid", "evt_5", "pay_5", 500000, captured=True
        )
        self.assertEqual(c.recovered_amount.paise, 500000)
        self.assertNotEqual(c.recovered_amount, c.revenue_at_risk)

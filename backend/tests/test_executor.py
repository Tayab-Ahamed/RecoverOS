import unittest

from app.domain.errors import PolicyViolation
from app.domain.states import CaseState
from app.policies.engine import Decision
from tests import factories as f


def decision(allowed=True, human=False):
    return Decision(
        id="dec_test",
        allowed=allowed,
        requires_human_approval=human,
        policy_version_id="v1",
        reasons=("test",),
    )


class TestExecutorAuthorization(unittest.TestCase):
    """Invariant 2: no outbound action without authorization."""

    def setUp(self):
        self.sys = f.System()
        self.customer = f.customer()

    def _approved(self):
        c = f.case()
        c.state = CaseState.APPROVED
        return c

    def test_refuses_a_denial(self):
        with self.assertRaises(PolicyViolation):
            self.sys.executor.execute(
                self._approved(), f.plan(), self.customer, decision(allowed=False)
            )
        self.assertEqual(self.sys.provider.create_calls, 0)

    def test_refuses_when_case_is_not_approved(self):
        with self.assertRaises(PolicyViolation):
            self.sys.executor.execute(f.case(), f.plan(), self.customer, decision())
        self.assertEqual(self.sys.provider.create_calls, 0)

    def test_refuses_high_value_without_human_approval(self):
        c = f.case()
        c.state = CaseState.AWAITING_APPROVAL
        with self.assertRaises(PolicyViolation):
            self.sys.executor.execute(c, f.plan(), self.customer, decision(human=True))
        self.assertEqual(self.sys.provider.create_calls, 0)

    def test_authorized_execution_creates_one_link(self):
        c = self._approved()
        self.sys.executor.execute(c, f.plan(), self.customer, decision())
        self.assertEqual(self.sys.provider.create_calls, 1)
        self.assertEqual(c.state, CaseState.AWAITING_PAYMENT)
        self.assertEqual(c.attempts, 1)
        self.assertEqual(c.contacts_made, 1)

    def test_action_is_audited_with_decision_and_policy_version(self):
        c = self._approved()
        self.sys.executor.execute(c, f.plan(), self.customer, decision())
        actions = [
            r for r in self.sys.audit.for_case(c.id) if r.action == "PAYMENT_LINK_CREATED"
        ]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].decision_id, "dec_test")
        self.assertEqual(actions[0].policy_version_id, "v1")

    def test_discount_reduces_link_amount(self):
        c = self._approved()
        self.sys.executor.execute(c, f.plan(discount=10.0), self.customer, decision())
        link = self.sys.provider.fetch_payment_link(c.external_link_id)
        self.assertEqual(link.amount.paise, 849900 - 84990)

    def test_stop_plan_performs_no_outbound_action(self):
        from app.domain.entities import InterventionType

        c = self._approved()
        self.sys.executor.execute(
            c, f.plan(InterventionType.STOP, contact=False), self.customer, decision()
        )
        self.assertEqual(self.sys.provider.create_calls, 0)
        self.assertEqual(c.state, CaseState.APPROVED)

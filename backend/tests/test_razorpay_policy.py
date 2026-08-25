"""The Razorpay-derived policy rules, tested through the real PolicyEngine.

These go through PolicyEngine.authorize rather than calling the rules module
directly, because the property that matters is that the guard cannot be
bypassed, not merely that the function returns the right string.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from app.domain.entities import (
    Customer,
    DataProvenance,
    FailureReason,
    InterventionPlan,
    InterventionType,
    RecoveryCase,
    RiskEvent,
    RiskEventType,
)
from app.domain.money import Money
from app.domain.states import Actor
from app.policies.engine import PolicyEngine


def make_case(metadata: dict | None = None) -> RecoveryCase:
    event = RiskEvent(
        id="evt_test",
        customer_id="cust_test",
        event_type=RiskEventType.PAYMENT_FAILED,
        amount=Money(250000),
        reason=FailureReason.INSUFFICIENT_FUNDS,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        provenance=DataProvenance.LIVE_TEST_MODE,
        metadata=metadata or {},
    )
    return RecoveryCase(id="case_test", customer_id="cust_test", event=event)


def make_customer() -> Customer:
    return Customer(
        id="cust_test",
        name="Test Customer",
        email="test@example.com",
        contact="+919000090000",
        lifetime_value=Money(5000000),
    )


def make_plan(intervention: InterventionType) -> InterventionPlan:
    return InterventionPlan(
        intervention=intervention,
        discount_percentage=0.0,
        contact_customer=True,
        rationale="test plan for policy evaluation",
        produced_by=Actor.STRATEGIST_AGENT,
        is_llm_output=False,
    )


class TestGatewayWindowRule(unittest.TestCase):
    def setUp(self):
        self.engine = PolicyEngine()

    def test_contact_denied_while_razorpay_is_still_auto_retrying(self):
        case = make_case({"subscription_status": "pending", "days_since_failure": 0.5})
        decision = self.engine.authorize(
            case, make_plan(InterventionType.PAYMENT_LINK), make_customer()
        )
        self.assertFalse(decision.allowed)
        self.assertIn("gateway_owns_retry_window", decision.rule_ids)

    def test_contact_allowed_once_the_ladder_is_exhausted(self):
        case = make_case({"subscription_status": "pending", "days_since_failure": 4.0})
        decision = self.engine.authorize(
            case, make_plan(InterventionType.PAYMENT_LINK), make_customer()
        )
        self.assertTrue(decision.allowed)

    def test_contact_allowed_when_subscription_is_halted(self):
        case = make_case({"subscription_status": "halted", "days_since_failure": 3.0})
        decision = self.engine.authorize(
            case, make_plan(InterventionType.PAYMENT_LINK), make_customer()
        )
        self.assertTrue(decision.allowed)

    def test_stop_is_still_permitted_inside_the_gateway_window(self):
        # The system must never be unable to stop, whatever the provider is doing.
        case = make_case({"subscription_status": "pending", "days_since_failure": 0.1})
        decision = self.engine.authorize(
            case, make_plan(InterventionType.STOP), make_customer()
        )
        self.assertTrue(decision.allowed)


class TestMandateRules(unittest.TestCase):
    def setUp(self):
        self.engine = PolicyEngine()

    def test_subscription_recovery_denied_without_a_mandate(self):
        case = make_case({"has_mandate": False})
        decision = self.engine.authorize(
            case, make_plan(InterventionType.SUBSCRIPTION_RECOVERY), make_customer()
        )
        self.assertFalse(decision.allowed)
        self.assertIn("requires_existing_mandate", decision.rule_ids)

    def test_mandate_debit_denied_without_24h_pre_debit_notification(self):
        case = make_case({"has_mandate": True, "pre_debit_notification_hours": 2.0})
        decision = self.engine.authorize(
            case, make_plan(InterventionType.SUBSCRIPTION_RECOVERY), make_customer()
        )
        self.assertFalse(decision.allowed)
        self.assertIn("rbi_pre_debit_notification", decision.rule_ids)

    def test_mandate_debit_allowed_with_compliant_notice(self):
        case = make_case({"has_mandate": True, "pre_debit_notification_hours": 26.0})
        decision = self.engine.authorize(
            case, make_plan(InterventionType.SUBSCRIPTION_RECOVERY), make_customer()
        )
        self.assertTrue(decision.allowed)

    def test_missing_notification_record_is_treated_as_a_violation(self):
        case = make_case({"has_mandate": True})
        decision = self.engine.authorize(
            case, make_plan(InterventionType.SUBSCRIPTION_RECOVERY), make_customer()
        )
        self.assertFalse(decision.allowed)


class TestHardDeclineRule(unittest.TestCase):
    def setUp(self):
        self.engine = PolicyEngine()

    def test_hard_decline_on_unchanged_instrument_is_denied(self):
        case = make_case({"decline_class": "HARD"})
        decision = self.engine.authorize(
            case, make_plan(InterventionType.PAYMENT_LINK), make_customer()
        )
        self.assertFalse(decision.allowed)
        self.assertIn("hard_decline_same_instrument", decision.rule_ids)

    def test_hard_decline_allowed_once_instrument_is_updated(self):
        case = make_case({"decline_class": "HARD", "instrument_updated": True})
        decision = self.engine.authorize(
            case, make_plan(InterventionType.PAYMENT_LINK), make_customer()
        )
        self.assertTrue(decision.allowed)

    def test_soft_decline_is_unaffected(self):
        case = make_case({"decline_class": "SOFT"})
        decision = self.engine.authorize(
            case, make_plan(InterventionType.PAYMENT_LINK), make_customer()
        )
        self.assertTrue(decision.allowed)


class TestSyntheticDataIsUnaffected(unittest.TestCase):
    def test_no_metadata_means_no_new_denials(self):
        # The benchmark carries none of these provider keys, so the new rules
        # must be completely inert there. If this fails, the headline numbers
        # moved for a reason unrelated to decision quality.
        engine = PolicyEngine()
        decision = engine.authorize(
            make_case({}), make_plan(InterventionType.PAYMENT_LINK), make_customer()
        )
        self.assertTrue(decision.allowed)
        for rule in (
            "gateway_owns_retry_window",
            "rbi_pre_debit_notification",
            "requires_existing_mandate",
            "hard_decline_same_instrument",
        ):
            self.assertNotIn(rule, decision.rule_ids)


if __name__ == "__main__":
    unittest.main()

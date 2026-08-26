"""Unit tests for the Promise-to-Pay (PTP) lifecycle tracker.

Tests verify:
1. PTP is a deterministic denial constraint (ptp_active_grace_period).
2. PolicyEngine.authorize() is pure, deterministic, and idempotent.
3. Strict fulfillment matching (exact case AND exact amount in paise).
4. Partial payment / amount mismatch before due date remains PENDING.
5. Timezone-aware date validation (naive datetimes strictly rejected).
6. Horizon cap (30 days) and broken promise limits (2 broken max).
7. Auditing for PTP_RECORDED, PTP_FULFILLED, PTP_BROKEN.
8. REST API endpoints for PTP registration and retrieval.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.entities import (
    Customer,
    FailureReason,
    InterventionPlan,
    InterventionType,
    Money,
    PromiseToPay,
    RecoveryCase,
    RiskEvent,
    RiskEventType,
    new_id,
)
from app.domain.states import Actor, CaseState, PromiseStatus
from app.integrations.mock_razorpay import MockRazorpayProvider
from app.policies.config import PolicyRules
from app.policies.engine import PolicyEngine
from app.services.audit import AuditLog
from app.services.executor import RecoveryExecutor
from app.services.orchestrator import RecoveryOrchestrator
from app.services.state_machine import StateMachine
from app.services.verifier import OutcomeVerifier
from tests import factories as f
from tests.optional_deps import HAS_FASTAPI, REQUIRES_FASTAPI

if HAS_FASTAPI:  # pragma: no branch - import guard
    from fastapi.testclient import TestClient  # noqa: E402

    from app.api.deps import set_clock  # noqa: E402
    from app.main import app  # noqa: E402


class PromiseToPayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock_time = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
        self.clock = lambda: self.clock_time
        self.audit = AuditLog()
        self.sm = StateMachine(self.audit)
        self.policy = PolicyEngine(clock=self.clock)
        self.provider = MockRazorpayProvider(seed="test")
        self.executor = RecoveryExecutor(self.provider, self.sm, self.audit)
        self.verifier = OutcomeVerifier(self.sm, self.audit)
        self.orch = RecoveryOrchestrator(
            policy=self.policy,
            executor=self.executor,
            state_machine=self.sm,
            audit=self.audit,
        )

        self.customer = Customer(
            id="cust_ptp_test",
            name="Aarav Patel",
            email="aarav@example.invalid",
            contact="+919876543210",
            lifetime_value=Money.from_rupees(50000),
        )

    def _make_case(self, rupees: int = 5000) -> RecoveryCase:
        event = RiskEvent(
            id=new_id("evt"),
            customer_id=self.customer.id,
            event_type=RiskEventType.PAYMENT_FAILED,
            amount=Money.from_rupees(rupees),
            reason=FailureReason.INSUFFICIENT_FUNDS,
            occurred_at=self.clock_time,
        )
        return RecoveryCase(id=new_id("case"), customer_id=self.customer.id, event=event)

    # ------------------------------------------------------------------ #
    # 1. Deterministic Denial & Pure Authorization
    # ------------------------------------------------------------------ #

    def test_active_ptp_denies_customer_contact(self) -> None:
        case = self._make_case(5000)
        due_date = self.clock_time + timedelta(days=3)
        self.orch.record_promise_to_pay(
            case=case,
            amount=case.revenue_at_risk,
            promise_due_date=due_date,
            customer=self.customer,
            notes="Customer promised to pay on Monday",
        )

        plan = InterventionPlan(
            intervention=InterventionType.PAYMENT_LINK,
            discount_percentage=0.0,
            contact_customer=True,
            rationale="Test plan",
            produced_by=Actor.STRATEGIST_AGENT,
            is_llm_output=False,
        )

        decision = self.policy.authorize(case, plan, self.customer)
        self.assertFalse(decision.allowed)
        self.assertIn("ptp_active_grace_period", decision.rule_ids)
        self.assertEqual(case.promise_to_pay.status, PromiseStatus.PENDING)

    def test_authorize_is_pure_and_idempotent(self) -> None:
        """PolicyEngine.authorize() must never mutate the case or promise state."""
        case = self._make_case(5000)
        due_date = self.clock_time + timedelta(days=3)
        self.orch.record_promise_to_pay(
            case=case,
            amount=case.revenue_at_risk,
            promise_due_date=due_date,
            customer=self.customer,
        )

        plan = InterventionPlan(
            intervention=InterventionType.PAYMENT_LINK,
            discount_percentage=0.0,
            contact_customer=True,
            rationale="Test plan",
            produced_by=Actor.STRATEGIST_AGENT,
            is_llm_output=False,
        )

        dec1 = self.policy.authorize(case, plan, self.customer)
        dec2 = self.policy.authorize(case, plan, self.customer)

        self.assertEqual(dec1.allowed, dec2.allowed)
        self.assertEqual(dec1.rule_ids, dec2.rule_ids)
        self.assertEqual(case.promise_to_pay.status, PromiseStatus.PENDING)
        self.assertEqual(case.broken_promises_count, 0)

    def test_stop_action_permitted_during_active_ptp(self) -> None:
        case = self._make_case(5000)
        due_date = self.clock_time + timedelta(days=3)
        self.orch.record_promise_to_pay(
            case=case,
            amount=case.revenue_at_risk,
            promise_due_date=due_date,
            customer=self.customer,
        )

        stop_plan = InterventionPlan(
            intervention=InterventionType.STOP,
            discount_percentage=0.0,
            contact_customer=False,
            rationale="Stop intervention",
            produced_by=Actor.STRATEGIST_AGENT,
            is_llm_output=False,
        )

        decision = self.policy.authorize(case, stop_plan, self.customer)
        self.assertTrue(decision.allowed)

    # ------------------------------------------------------------------ #
    # 2. Expiration and State Transitions
    # ------------------------------------------------------------------ #

    def test_expired_ptp_marks_broken_in_advance_and_allows_dunning(self) -> None:
        case = self._make_case(5000)
        due_date = self.clock_time + timedelta(days=2)
        self.orch.record_promise_to_pay(
            case=case,
            amount=case.revenue_at_risk,
            promise_due_date=due_date,
            customer=self.customer,
        )

        # Move clock 3 days forward (past the due date)
        self.clock_time = self.clock_time + timedelta(days=3)

        # Advance drives the state machine and detects expired promise
        self.orch.advance(case, self.customer)

        self.assertEqual(case.promise_to_pay.status, PromiseStatus.BROKEN)
        self.assertEqual(case.broken_promises_count, 1)

        # Verify PTP_BROKEN audit record
        broken_records = [r for r in self.audit.for_case(case.id) if r.action == "PTP_BROKEN"]
        self.assertEqual(len(broken_records), 1)

    # ------------------------------------------------------------------ #
    # 3. Strict Fulfillment Matching
    # ------------------------------------------------------------------ #

    def test_exact_case_and_amount_fulfills_ptp(self) -> None:
        case = self._make_case(5000)
        due_date = self.clock_time + timedelta(days=2)
        ptp = self.orch.record_promise_to_pay(
            case=case,
            amount=Money.from_rupees(5000),
            promise_due_date=due_date,
            customer=self.customer,
        )

        case.state = CaseState.AWAITING_PAYMENT

        # Webhook / verifier receives exact amount on exact case
        self.verifier.verify(
            case=case,
            event_type="payment.captured",
            external_event_id="evt_cap_123",
            payment_id="pay_12345",
            amount_paise=500000,  # Rs 5,000.00
            captured=True,
        )

        self.assertEqual(case.state, CaseState.RECOVERED)
        self.assertEqual(ptp.status, PromiseStatus.FULFILLED)
        self.assertEqual(ptp.fulfilled_evidence_id, "pay_12345")
        self.assertIsNotNone(ptp.fulfilled_at)

        fulfilled_records = [
            r for r in self.audit.for_case(case.id) if r.action == "PTP_FULFILLED"
        ]
        self.assertEqual(len(fulfilled_records), 1)

    def test_payment_for_different_case_does_not_fulfill_ptp(self) -> None:
        case_a = self._make_case(5000)
        case_b = self._make_case(5000)

        due_date = self.clock_time + timedelta(days=2)
        ptp_a = self.orch.record_promise_to_pay(
            case=case_a,
            amount=Money.from_rupees(5000),
            promise_due_date=due_date,
            customer=self.customer,
        )

        case_b.state = CaseState.AWAITING_PAYMENT
        self.verifier.verify(
            case=case_b,
            event_type="payment.captured",
            external_event_id="evt_cap_b",
            payment_id="pay_case_b",
            amount_paise=500000,
            captured=True,
        )

        self.assertEqual(case_b.state, CaseState.RECOVERED)
        # Case A promise remains untouched and PENDING
        self.assertEqual(ptp_a.status, PromiseStatus.PENDING)
        self.assertIsNone(ptp_a.fulfilled_at)

    def test_mismatched_amount_does_not_fulfill_ptp_and_stays_pending(self) -> None:
        """Partial payment before due date must NOT fulfill, and must NOT mark BROKEN prematurely."""
        case = self._make_case(5000)
        due_date = self.clock_time + timedelta(days=3)
        ptp = self.orch.record_promise_to_pay(
            case=case,
            amount=Money.from_rupees(5000),
            promise_due_date=due_date,
            customer=self.customer,
        )

        case.state = CaseState.AWAITING_PAYMENT

        # Partial capture of Rs 2,500
        self.verifier.verify(
            case=case,
            event_type="payment.captured",
            external_event_id="evt_cap_partial",
            payment_id="pay_partial_123",
            amount_paise=250000,
            captured=True,
        )

        # Case is recovered for the partial amount, but promise is not fulfilled and not broken yet
        self.assertEqual(ptp.status, PromiseStatus.PENDING)
        self.assertIsNone(ptp.fulfilled_at)

        partial_records = [
            r for r in self.audit.for_case(case.id) if r.action == "PTP_PARTIAL_PAYMENT"
        ]
        self.assertEqual(len(partial_records), 1)

    # ------------------------------------------------------------------ #
    # 4. Defensive Boundary Controls & Invariants
    # ------------------------------------------------------------------ #

    def test_naive_promise_due_date_is_rejected(self) -> None:
        case = self._make_case(5000)
        naive_dt = datetime(2026, 8, 25, 12, 0, 0)  # no tzinfo!

        with self.assertRaises(ValueError) as ctx:
            self.orch.record_promise_to_pay(
                case=case,
                amount=case.revenue_at_risk,
                promise_due_date=naive_dt,
            )
        self.assertIn("timezone-aware", str(ctx.exception))

    def test_timezone_aware_ist_date_is_accepted(self) -> None:
        case = self._make_case(5000)
        ist_dt = datetime(2026, 8, 22, 17, 30, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        ptp = self.orch.record_promise_to_pay(
            case=case,
            amount=case.revenue_at_risk,
            promise_due_date=ist_dt,
        )
        self.assertEqual(ptp.status, PromiseStatus.PENDING)

    def test_past_due_date_is_rejected(self) -> None:
        case = self._make_case(5000)
        past_dt = self.clock_time - timedelta(hours=1)
        with self.assertRaises(ValueError) as ctx:
            self.orch.record_promise_to_pay(
                case=case,
                amount=case.revenue_at_risk,
                promise_due_date=past_dt,
            )
        self.assertIn("future", str(ctx.exception))

    def test_horizon_exceeding_30_days_is_rejected(self) -> None:
        case = self._make_case(5000)
        far_future = self.clock_time + timedelta(days=31)
        with self.assertRaises(ValueError) as ctx:
            self.orch.record_promise_to_pay(
                case=case,
                amount=case.revenue_at_risk,
                promise_due_date=far_future,
            )
        self.assertIn("exceeds policy cap", str(ctx.exception))

    def test_consecutive_broken_promises_limit_refuses_grace(self) -> None:
        case = self._make_case(5000)
        case.broken_promises_count = 2  # Already broken max allowed

        due_date = self.clock_time + timedelta(days=2)
        with self.assertRaises(ValueError) as ctx:
            self.orch.record_promise_to_pay(
                case=case,
                amount=case.revenue_at_risk,
                promise_due_date=due_date,
            )
        self.assertIn("broken promises", str(ctx.exception))

    def test_ptp_recorded_audit_event(self) -> None:
        case = self._make_case(5000)
        due_date = self.clock_time + timedelta(days=2)
        ptp = self.orch.record_promise_to_pay(
            case=case,
            amount=case.revenue_at_risk,
            promise_due_date=due_date,
            notes="Customer telephone call",
        )

        records = [r for r in self.audit.for_case(case.id) if r.action == "PTP_RECORDED"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].actor, Actor.HUMAN)
        self.assertIn(ptp.id, records[0].detail)


# ------------------------------------------------------------------ #
# 5. REST API Integration Tests
# ------------------------------------------------------------------ #


@unittest.skipUnless(HAS_FASTAPI, REQUIRES_FASTAPI)
class PromiseToPayApiTests(unittest.TestCase):
    def setUp(self) -> None:
        set_clock(f.fixed_clock)
        self.client = TestClient(app)
        self.client.post("/api/v1/demo/reset")
        self.client.post("/api/v1/demo/seed")

    def tearDown(self) -> None:
        set_clock(None)

    def test_ptp_api_registration_and_retrieval(self) -> None:
        cases_resp = self.client.get("/api/v1/cases?page=1&page_size=1")
        self.assertEqual(cases_resp.status_code, 200)
        cases = cases_resp.json()["results"]
        self.assertTrue(len(cases) > 0)
        case_id = cases[0]["id"]

        # 1. Register PTP
        due_date = (f.fixed_clock() + timedelta(days=3)).isoformat()
        ptp_payload = {
            "amount_rupees": 2499.0,
            "promise_due_date": due_date,
            "notes": "Committed via phone",
        }
        res = self.client.post(f"/api/v1/cases/{case_id}/ptp", json=ptp_payload)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["status"], "recorded")
        self.assertEqual(data["promise"]["status"], "PENDING")
        self.assertEqual(data["promise"]["amount"]["display"], "Rs 2499.00")

        # 2. Get PTP
        get_res = self.client.get(f"/api/v1/cases/{case_id}/ptp")
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["promise"]["status"], "PENDING")

        # 3. Naive date rejection
        bad_payload = {
            "amount_rupees": 2499.0,
            "promise_due_date": "2026-08-25T12:00:00",  # naive
        }
        bad_res = self.client.post(f"/api/v1/cases/{case_id}/ptp", json=bad_payload)
        self.assertEqual(bad_res.status_code, 400)
        self.assertIn("timezone-aware", bad_res.json()["detail"])


if __name__ == "__main__":
    unittest.main()

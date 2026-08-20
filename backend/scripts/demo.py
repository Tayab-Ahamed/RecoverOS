#!/usr/bin/env python3
"""Narrated demo of the four scenarios that matter.

Runs entirely offline against the mock provider, so it is safe to run on stage
with no network and no credentials.

    python -m scripts.demo
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.domain.entities import (  # noqa: E402
    Customer,
    FailureReason,
    RecoveryCase,
    RiskEvent,
    RiskEventType,
    new_id,
    utcnow,
)
from app.domain.money import Money  # noqa: E402
from app.domain.states import CaseState  # noqa: E402
from app.integrations.idempotency import InMemoryIdempotencyStore  # noqa: E402
from app.integrations.mock_razorpay import MockRazorpayProvider  # noqa: E402
from app.integrations.signature import compute_signature  # noqa: E402
from app.policies.engine import PolicyEngine  # noqa: E402
from app.services.audit import AuditLog  # noqa: E402
from app.services.executor import RecoveryExecutor  # noqa: E402
from app.services.orchestrator import RecoveryOrchestrator  # noqa: E402
from app.services.state_machine import StateMachine  # noqa: E402
from app.services.verifier import OutcomeVerifier  # noqa: E402
from app.webhooks.handler import WebhookHandler  # noqa: E402

SECRET = "demo_secret"
RULE = "=" * 74


def build(approver=None):
    audit = AuditLog()
    sm = StateMachine(audit)
    provider = MockRazorpayProvider(seed="demo")
    executor = RecoveryExecutor(provider, sm, audit)
    verifier = OutcomeVerifier(sm, audit)
    cases: dict[str, RecoveryCase] = {}
    handler = WebhookHandler(SECRET, verifier, InMemoryIdempotencyStore(), cases.get)
    orch = RecoveryOrchestrator(
        policy=PolicyEngine(),
        executor=executor,
        state_machine=sm,
        audit=audit,
        approver=approver,
    )
    return audit, provider, cases, handler, orch


def make_case(cases, rupees, reason, event_type=RiskEventType.PAYMENT_FAILED):
    event = RiskEvent(
        id=new_id("evt"),
        customer_id="cust_demo",
        event_type=event_type,
        amount=Money.from_rupees(rupees),
        reason=reason,
        occurred_at=utcnow(),
    )
    case = RecoveryCase(id=new_id("case"), customer_id=event.customer_id, event=event)
    cases[case.id] = case
    return case


def deliver(handler, provider, case, paid: bool, n: int):
    event = (
        provider.paid_event(case.external_link_id)
        if paid
        else provider.failed_event(case.external_link_id)
    )
    raw = json.dumps(event).encode()
    return handler.handle(raw, compute_signature(raw, SECRET), f"evt_{case.id}_{n}")


def show(audit, case, title, takeaway):
    print(f"\n{RULE}\n{title}\n{RULE}")
    print(f"case {case.id}   revenue at risk Rs {case.revenue_at_risk.rupees_str}")
    if case.diagnosis:
        print(f"diagnosis: {case.diagnosis.cause} "
              f"(p={case.diagnosis.recovery_probability:.2f})")
        print(f"  {case.diagnosis.rationale}")
    if case.plan:
        print(f"proposal: {case.plan.intervention} -> {case.plan.rationale}")
    print(f"\nfinal state: {case.state}")
    print(f"attempts {case.attempts}   contacts {case.contacts_made}")
    if case.recovered_amount:
        print(f"RECOVERED: Rs {case.recovered_amount.rupees_str} "
              f"(evidence {case.evidence.external_payment_id}, "
              f"{case.evidence.raw_event_type})")
    print("\naudit trail:")
    for record in audit.for_case(case.id):
        print(f"  {record.render()}")
    print(f"\n>> {takeaway}")


def scenario_a():
    audit, provider, cases, handler, orch = build()
    case = make_case(cases, 8499, FailureReason.CARD_EXPIRED)
    customer = Customer(
        id="cust_demo",
        name="Priya Sharma",
        email="priya@example.invalid",
        contact="+919000000001",
        lifetime_value=Money.from_rupees(120000),
    )
    orch.advance(case, customer)
    deliver(handler, provider, case, True, 1)
    show(
        audit,
        case,
        "SCENARIO A  recoverable failure, money actually recovered",
        "The loop executed. Recovery was declared only after a captured "
        "payment event, by the verifier, not by the agent that acted.",
    )


def scenario_b():
    audit, provider, cases, handler, orch = build()
    case = make_case(cases, 4999, FailureReason.CARD_DECLINED)
    customer = Customer(
        id="cust_demo",
        name="Arjun Nair",
        email="arjun@example.invalid",
        contact="+919000000002",
        lifetime_value=Money.from_rupees(30000),
    )
    orch.advance(case, customer)
    n = 0
    while case.state is CaseState.AWAITING_PAYMENT:
        n += 1
        deliver(handler, provider, case, False, n)
        if case.state is CaseState.FAILED:
            orch.handle_failure(case, customer)
    show(
        audit,
        case,
        "SCENARIO B  unrecoverable, stopped and escalated",
        "The system stopped itself. Bounded attempts, bounded contacts, then "
        "a compliant handover to a human. It did not keep trying forever.",
    )


def scenario_c():
    audit, provider, cases, handler, orch = build()
    case = make_case(cases, 1299, FailureReason.INSUFFICIENT_FUNDS)
    customer = Customer(
        id="cust_demo",
        name="Meera Iyer",
        email="meera@example.invalid",
        contact="+919000000003",
        lifetime_value=Money.from_rupees(9000),
        opted_out=True,
    )
    orch.advance(case, customer)
    show(
        audit,
        case,
        "SCENARIO C  policy refusal (the most important scenario)",
        "Recoverable revenue was deliberately left on the table because the "
        "customer opted out. Zero provider calls were made. An AI that cannot "
        "be told no is not deployable in payments.",
    )
    print(f"provider calls made: {provider.create_calls}")


def scenario_d():
    audit, provider, cases, handler, orch = build(approver=None)
    case = make_case(cases, 75000, FailureReason.TECHNICAL_ERROR)
    customer = Customer(
        id="cust_demo",
        name="Rohan Gupta",
        email="rohan@example.invalid",
        contact="+919000000004",
        lifetime_value=Money.from_rupees(900000),
    )
    orch.advance(case, customer)
    show(
        audit,
        case,
        "SCENARIO D  high value, held for human approval",
        "Above the review threshold the system stops and waits. No approver "
        "is configured here, so it holds indefinitely rather than "
        "self-approving.",
    )
    print(f"provider calls made: {provider.create_calls}")


def main() -> int:
    print("\nRecoverOS demo   SYNTHETIC DATA, MOCK PROVIDER, NO NETWORK CALLS")
    scenario_a()
    scenario_b()
    scenario_c()
    scenario_d()
    print(f"\n{RULE}\nAI proposes. Deterministic software authorizes. "
          f"The provider executes. Webhooks verify.\n{RULE}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

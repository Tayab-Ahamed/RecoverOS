"""Demo control surface, for seeding and driving the system without a provider.

Every route here is gated on a non-production environment. These are
affordances for a reviewer, not product features.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Body, HTTPException

from app.api.deps import get_container, reset_container
from app.api.schemas import case_out
from app.detection.rules import detect
from app.domain.entities import (
    Customer,
    DataProvenance,
    FailureReason,
    RiskEvent,
    RiskEventType,
)
from app.domain.money import Money
from app.domain.states import CaseState
from app.evaluation.generator import demo_dataset, generate
from app.integrations.signature import compute_signature

router = APIRouter(prefix="/demo", tags=["demo"])


def _guard() -> None:
    if get_container().settings.is_production:
        raise HTTPException(404, "not found")


@router.post("/reset")
def reset() -> dict:
    _guard()
    reset_container()
    return {"status": "reset"}


@router.post("/seed")
def seed(events: int = Body(default=40, embed=True), seed: int = Body(default=7, embed=True)) -> dict:
    """Load a labelled synthetic dataset and run detection over it."""
    _guard()
    # Demo seeding is intentionally repeatable. This also keeps older frontend
    # bundles safe if they call seed directly without an explicit reset.
    reset_container()
    container = get_container()
    dataset = demo_dataset() if events == 40 and seed == 7 else generate(events, seed)

    for customer in dataset.customers.values():
        container.customers.add(customer)

    signals = detect(dataset.events, dataset.customers, dataset.generated_at)
    for signal in signals:
        case = container.orchestrator.open_case(
            signal, DataProvenance.SYNTHETIC, dataset.run_id
        )
        container.cases.add(case)

    container.persist()

    return {
        "dataset_run_id": dataset.run_id,
        "seed": dataset.seed,
        "provenance": str(DataProvenance.SYNTHETIC),
        "customers": len(dataset.customers),
        "cases_detected": len(signals),
    }


@router.post("/live-test-case")
def live_test_case(
    amount_rupees: int = Body(default=4999, embed=True),
    reason: str = Body(default="CARD_EXPIRED", embed=True),
) -> dict:
    """Create one explicitly labelled LIVE_TEST_MODE recovery case.

    This endpoint is intentionally separate from synthetic seeding so the
    dashboard cannot silently blend benchmark outcomes with a real Test Mode
    payment. It requires the Razorpay adapter and never creates Live traffic.
    """
    _guard()
    current = get_container()
    if current.settings.payment_provider != "razorpay":
        raise HTTPException(409, "set PAYMENT_PROVIDER=razorpay for a live Test Mode case")
    if amount_rupees < 100 or amount_rupees > 50_000:
        raise HTTPException(400, "amount_rupees must be between 100 and 50000")
    try:
        failure_reason = FailureReason(reason.upper())
    except ValueError as exc:
        raise HTTPException(400, f"unknown failure reason: {reason}") from exc

    # Reset first so a live Test Mode run cannot coexist with synthetic demo
    # rows in the same reporting window.
    reset_container()
    container = get_container()
    customer = Customer(
        id="cust_live_test_001",
        name="Buildathon Test Customer",
        email="buildathon@example.invalid",
        contact="+919000000000",
        lifetime_value=Money.from_rupees(250_000),
        provenance=DataProvenance.LIVE_TEST_MODE,
    )
    event = RiskEvent(
        id="live_test_payment_001",
        customer_id=customer.id,
        event_type=RiskEventType.PAYMENT_FAILED,
        amount=Money.from_rupees(amount_rupees),
        reason=failure_reason,
        occurred_at=datetime.now(UTC),
        provenance=DataProvenance.LIVE_TEST_MODE,
        external_ref="razorpay_test_mode",
    )
    customer_store = container.customers
    customer_store.add(customer)
    signal = detect([event], {customer.id: customer}, event.occurred_at)[0]
    case = container.orchestrator.open_case(signal, DataProvenance.LIVE_TEST_MODE, "live_test_mode")
    container.cases.add(case)
    container.orchestrator.advance(case, customer)
    container.cases.add(case)
    container.persist()
    return {
        "provenance": str(DataProvenance.LIVE_TEST_MODE),
        "mode": "RAZORPAY_TEST_MODE_ONLY",
        "case": case_out(case),
        "next": "Open the returned Payment Link, complete it in Test Mode, then inspect the signed webhook audit trail.",
    }


@router.post("/run")
def run(limit: int = Body(default=25, embed=True)) -> dict:
    """Advance detected cases through the loop up to the point of action."""
    _guard()
    container = get_container()
    advanced = []
    for case in container.cases.all():
        if case.state is not CaseState.DETECTED:
            continue
        if len(advanced) >= limit:
            break
        customer = container.customers.get(case.customer_id)
        if customer is None:
            continue
        container.orchestrator.advance(case, customer)
        container.cases.add(case)
        advanced.append(case)
    container.persist()
    return {"advanced": len(advanced), "results": [case_out(c) for c in advanced]}


@router.post("/replay-webhook")
def replay_webhook(
    case_id: str = Body(embed=True),
    paid: bool | None = Body(default=None, embed=True),
) -> dict:
    """Deliver a correctly signed provider event without a public tunnel.

    This goes through the real signature and idempotency path, so it exercises
    production code rather than bypassing it.
    """
    _guard()
    container = get_container()
    if not container.settings.enable_local_webhook_replay:
        raise HTTPException(403, "ENABLE_LOCAL_WEBHOOK_REPLAY is false")
    if container.settings.payment_provider != "mock":
        raise HTTPException(409, "replay is only available with the mock provider")

    case = container.cases.get(case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    if not case.external_link_id:
        raise HTTPException(409, "case has no payment link to settle")

    import json

    if paid is None:
        if case.diagnosis is None:
            raise HTTPException(409, "case has no diagnosis")
        paid = container.provider.customer_will_pay(
            f"{case.event.id}:{case.attempts + 1}",
            case.diagnosis.recovery_probability,
        )
    event = (
        container.provider.paid_event(case.external_link_id)
        if paid
        else container.provider.failed_event(case.external_link_id)
    )
    raw = json.dumps(event).encode()
    secret = container.settings.razorpay_webhook_secret or "unset"
    result = container.webhooks.handle(
        raw, compute_signature(raw, secret), f"replay_{case.id}_{case.attempts}"
    )

    # SQL repositories return a fresh domain object during webhook lookup.
    # Persist that mutated verifier object, not the pre-webhook snapshot.
    updated_case = container.webhooks.last_case if result.case_id else None
    if updated_case is not None:
        case = updated_case

    if case.state is CaseState.FAILED:
        customer = container.customers.get(case.customer_id)
        if customer is not None:
            container.orchestrator.handle_failure(case, customer)

    container.cases.add(case)

    container.persist()

    return {"accepted": result.accepted, "reason": result.reason, "case": case_out(case)}

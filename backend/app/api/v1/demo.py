"""Demo control surface, for seeding and driving the system without a provider.

Every route here is gated on a non-production environment. These are
affordances for a reviewer, not product features.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from app.api.deps import get_container, reset_container
from app.api.schemas import case_out
from app.detection.rules import detect
from app.domain.entities import DataProvenance
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

    return {
        "dataset_run_id": dataset.run_id,
        "seed": dataset.seed,
        "provenance": str(DataProvenance.SYNTHETIC),
        "customers": len(dataset.customers),
        "cases_detected": len(signals),
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
        advanced.append(case)
    return {"advanced": len(advanced), "results": [case_out(c) for c in advanced]}


@router.post("/replay-webhook")
def replay_webhook(
    case_id: str = Body(embed=True),
    paid: bool = Body(default=True, embed=True),
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

    if case.state is CaseState.FAILED:
        customer = container.customers.get(case.customer_id)
        if customer is not None:
            container.orchestrator.handle_failure(case, customer)

    return {"accepted": result.accepted, "reason": result.reason, "case": case_out(case)}

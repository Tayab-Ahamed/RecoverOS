"""Case inspection endpoints.

Every case exposes its full audit trail, because a recovery number that cannot
be traced to a decision and a payment is not auditable.
"""

from __future__ import annotations

import csv
import io
import math
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import get_container
from app.api.schemas import audit_out, case_out
from app.domain.states import CaseState

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("")
def list_cases(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    state: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    reason: str | None = Query(default=None),
) -> dict:
    container = get_container()
    cases = container.cases.all()

    if state:
        try:
            wanted = CaseState(state.upper())
        except ValueError as exc:
            raise HTTPException(400, f"unknown state {state!r}") from exc
        cases = [c for c in cases if c.state is wanted]

    if event_type:
        cases = [c for c in cases if str(c.event.event_type).upper() == event_type.upper()]

    if reason:
        cases = [c for c in cases if str(c.event.reason).upper() == reason.upper()]

    cases.sort(key=lambda c: c.revenue_at_risk.paise, reverse=True)

    total = len(cases)
    pages = math.ceil(total / page_size) if total else 1
    offset = (page - 1) * page_size
    window = cases[offset: offset + page_size]

    return {
        "results": [case_out(c) for c in window],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


@router.get("/{case_id}")
def get_case(case_id: str) -> dict:
    container = get_container()
    case = container.cases.get(case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    return {
        "case": case_out(case),
        "audit_trail": [audit_out(r) for r in container.audit.for_case(case_id)],
    }


@router.get("/{case_id}/audit")
def get_case_audit(case_id: str) -> dict:
    container = get_container()
    if container.cases.get(case_id) is None:
        raise HTTPException(404, "case not found")
    return {"results": [audit_out(r) for r in container.audit.for_case(case_id)]}


@router.get("/{case_id}/audit.csv")
def audit_csv(case_id: str):
    """Export the audit trail for a case as a CSV file."""
    container = get_container()
    if container.cases.get(case_id) is None:
        raise HTTPException(404, "case not found")

    records = container.audit.for_case(case_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "case_id", "actor", "action", "from_state", "to_state",
        "detail", "at", "policy_version_id", "decision_id",
    ])
    for r in records:
        writer.writerow([
            r.id,
            r.case_id,
            str(r.actor),
            r.action,
            str(r.from_state) if r.from_state else "",
            str(r.to_state) if r.to_state else "",
            r.detail or "",
            r.at.isoformat(),
            r.policy_version_id or "",
            r.decision_id or "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=audit_{case_id}.csv"},
    )


class PromiseToPayRequest(BaseModel):
    amount_rupees: str | int = Field(..., description="Rupee string e.g. '2499.00' or integer rupees")
    promise_due_date: str = Field(..., description="ISO 8601 string with timezone offset")
    notes: str = ""


@router.post("/{case_id}/ptp")
def record_ptp(case_id: str, body: PromiseToPayRequest) -> dict:
    container = get_container()
    case = container.cases.get(case_id)
    if case is None:
        raise HTTPException(404, "case not found")

    try:
        due_dt = datetime.fromisoformat(body.promise_due_date)
    except ValueError as exc:
        raise HTTPException(400, f"invalid ISO 8601 date string: {body.promise_due_date}") from exc

    if due_dt.tzinfo is None:
        raise HTTPException(400, "promise_due_date must be timezone-aware (e.g. +05:30 or Z)")

    from app.api.schemas import promise_out
    from app.domain.money import Money

    try:
        amount = Money.from_rupees(str(body.amount_rupees))
    except Exception as exc:
        raise HTTPException(400, f"invalid money amount: {exc}") from exc

    customer = container.customers.get(case.customer_id)

    try:
        ptp = container.orchestrator.record_promise_to_pay(
            case=case,
            amount=amount,
            promise_due_date=due_dt,
            customer=customer,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    container.cases.add(case)
    container.persist()
    return {"status": "recorded", "promise": promise_out(ptp)}


@router.get("/{case_id}/ptp")
def get_ptp(case_id: str) -> dict:
    container = get_container()
    case = container.cases.get(case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    if case.promise_to_pay is None:
        raise HTTPException(404, "no promise to pay on this case")
    from app.api.schemas import promise_out

    return {"promise": promise_out(case.promise_to_pay)}

"""Human-in-the-loop endpoints.

These exist so that the approval gate is a real product surface rather than a
configuration flag nobody can see.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from app.api.deps import get_container
from app.api.schemas import case_out
from app.domain.errors import IllegalTransition
from app.domain.states import CaseState

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("")
def list_pending() -> dict:
    container = get_container()
    pending = [
        c for c in container.cases.all() if c.state is CaseState.AWAITING_APPROVAL
    ]
    pending.sort(key=lambda c: c.revenue_at_risk.paise, reverse=True)
    return {
        "total": len(pending),
        "total_value_paise": sum(c.revenue_at_risk.paise for c in pending),
        "results": [case_out(c) for c in pending],
    }


@router.post("/{case_id}/approve")
def approve(case_id: str, approver: str = Body(embed=True)) -> dict:
    container = get_container()
    case = container.cases.get(case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    customer = container.customers.get(case.customer_id)
    if customer is None:
        raise HTTPException(409, "customer record missing for this case")
    try:
        container.approvals.approve(case, customer, approver)
    except IllegalTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    container.persist()
    return {"case": case_out(case)}


@router.post("/{case_id}/deny")
def deny(
    case_id: str,
    approver: str = Body(embed=True),
    reason: str = Body(embed=True, default="no reason supplied"),
) -> dict:
    container = get_container()
    case = container.cases.get(case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    try:
        container.approvals.deny(case, approver, reason)
    except IllegalTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    container.persist()
    return {"case": case_out(case)}

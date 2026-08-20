"""Case inspection endpoints.

Every case exposes its full audit trail, because a recovery number that cannot
be traced to a decision and a payment is not auditable.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import get_container
from app.api.schemas import audit_out, case_out
from app.domain.states import CaseState

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("")
def list_cases(
    state: str | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict:
    container = get_container()
    cases = container.cases.all()

    if state:
        try:
            wanted = CaseState(state.upper())
        except ValueError as exc:
            raise HTTPException(400, f"unknown state {state!r}") from exc
        cases = [c for c in cases if c.state is wanted]

    cases.sort(key=lambda c: c.revenue_at_risk.paise, reverse=True)
    window = cases[offset : offset + limit]
    return {
        "total": len(cases),
        "limit": limit,
        "offset": offset,
        "results": [case_out(c) for c in window],
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

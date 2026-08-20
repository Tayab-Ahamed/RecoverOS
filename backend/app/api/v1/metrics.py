"""Aggregate recovery metrics.

Recovered revenue is summed from verified evidence only, never from cases that
merely reached a late state.
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter

from app.api.deps import get_container
from app.domain.money import Money
from app.domain.states import CaseState

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("")
def metrics() -> dict:
    container = get_container()
    cases = container.cases.all()

    at_risk = sum(c.revenue_at_risk.paise for c in cases)
    eligible = sum(
        c.revenue_at_risk.paise for c in cases if c.state is not CaseState.INELIGIBLE
    )
    # Invariant 1 at the reporting layer: only verified captures count.
    recovered = sum(
        c.evidence.amount.paise
        for c in cases
        if c.evidence is not None and c.evidence.captured
    )
    by_state = Counter(str(c.state) for c in cases)
    provenance = Counter(str(c.provenance) for c in cases)

    return {
        "cases": len(cases),
        "revenue_at_risk": {"paise": at_risk, "display": f"Rs {Money(at_risk).rupees_str}"},
        "eligible_revenue": {
            "paise": eligible,
            "display": f"Rs {Money(eligible).rupees_str}",
        },
        "recovered_revenue": {
            "paise": recovered,
            "display": f"Rs {Money(recovered).rupees_str}",
        },
        "recovery_rate": round(recovered / eligible, 4) if eligible else 0.0,
        "cases_by_state": dict(by_state),
        "data_provenance": dict(provenance),
        "audit_records": len(container.audit),
        "policy_version": container.policy.version.id,
        "policy_checksum": container.policy.version.checksum,
    }

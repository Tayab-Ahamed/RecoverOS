"""Response shaping. Amounts are exposed in paise as integers AND as a
formatted rupee string, so no client is ever tempted to do float maths on
money."""

from __future__ import annotations

from app.domain.entities import AuditRecord, RecoveryCase


def money_out(amount) -> dict | None:
    if amount is None:
        return None
    return {"paise": amount.paise, "display": f"Rs {amount.rupees_str}", "currency": "INR"}


def case_out(case: RecoveryCase) -> dict:
    return {
        "id": case.id,
        "customer_id": case.customer_id,
        "state": str(case.state),
        "provenance": str(case.provenance),
        "revenue_at_risk": money_out(case.revenue_at_risk),
        "recovered_amount": money_out(case.recovered_amount),
        "attempts": case.attempts,
        "contacts_made": case.contacts_made,
        "external_link_id": case.external_link_id,
        "event": {
            "id": case.event.id,
            "type": str(case.event.event_type),
            "reason": str(case.event.reason),
            "amount": money_out(case.event.amount),
            "occurred_at": case.event.occurred_at.isoformat(),
        },
        "diagnosis": (
            {
                "cause": str(case.diagnosis.cause),
                "recovery_probability": case.diagnosis.recovery_probability,
                "rationale": case.diagnosis.rationale,
                "produced_by": str(case.diagnosis.produced_by),
                "is_llm_output": case.diagnosis.is_llm_output,
                "confidence": case.diagnosis.confidence,
                "evidence": case.diagnosis.evidence,
                "risk_factors": case.diagnosis.risk_factors,
            }
            if case.diagnosis
            else None
        ),
        "plan": (
            {
                "intervention": str(case.plan.intervention),
                "discount_percentage": case.plan.discount_percentage,
                "rationale": case.plan.rationale,
                "produced_by": str(case.plan.produced_by),
                "is_llm_output": case.plan.is_llm_output,
                "confidence": case.plan.confidence,
                "evidence": case.plan.evidence,
                "alternatives_considered": case.plan.alternatives_considered,
                "expected_recovery_value": money_out(case.plan.expected_recovery_value),
            }
            if case.plan
            else None
        ),
        "evidence": (
            {
                "payment_id": case.evidence.external_payment_id,
                "event_id": case.evidence.external_event_id,
                "amount": money_out(case.evidence.amount),
                "captured": case.evidence.captured,
                "verified_at": case.evidence.verified_at.isoformat(),
                "event_type": case.evidence.raw_event_type,
            }
            if case.evidence
            else None
        ),
    }


def audit_out(record: AuditRecord) -> dict:
    return {
        "id": record.id,
        "case_id": record.case_id,
        "actor": str(record.actor),
        "action": record.action,
        "from_state": str(record.from_state) if record.from_state else None,
        "to_state": str(record.to_state) if record.to_state else None,
        "detail": record.detail,
        "at": record.at.isoformat(),
        "policy_version_id": record.policy_version_id,
        "decision_id": record.decision_id,
        "external_event_id": record.external_event_id,
    }

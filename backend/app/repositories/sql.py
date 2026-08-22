"""SQLAlchemy persistence adapters for domain aggregates.

The adapters deliberately expose the same small surface as the in-memory
repositories. JSON is used only for nested agent output and event metadata;
money and lifecycle state remain typed columns with database constraints.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.domain.entities import (
    AuditRecord,
    Customer,
    DataProvenance,
    Diagnosis,
    FailureReason,
    InterventionPlan,
    InterventionType,
    PaymentEvidence,
    RecoveryCase,
    RiskEvent,
    RiskEventType,
)
from app.domain.money import Money
from app.domain.states import Actor, CaseState
from app.models.sql import Customer as CustomerRow
from app.models.sql import RecoveryCase as CaseRow
from app.models.sql import RiskEvent as EventRow
from app.models.sql import PaymentEvidence as EvidenceRow
from app.models.sql import AuditRecord as AuditRow
from sqlalchemy import select


def _dt(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class SqlCustomerRepository:
    def __init__(self, session) -> None:
        self.session = session

    def add(self, customer: Customer) -> Customer:
        row = self.session.get(CustomerRow, customer.id) or CustomerRow(id=customer.id)
        row.name = customer.name
        row.email = customer.email
        row.contact = customer.contact
        row.lifetime_value_paise = customer.lifetime_value.paise
        row.opted_out = customer.opted_out
        row.contacts_this_window = customer.contacts_this_window
        row.provenance = str(customer.provenance)
        self.session.add(row)
        return customer

    def get(self, customer_id: str) -> Customer | None:
        row = self.session.get(CustomerRow, customer_id)
        if row is None:
            return None
        return Customer(
            id=row.id, name=row.name, email=row.email, contact=row.contact,
            lifetime_value=Money(row.lifetime_value_paise), opted_out=row.opted_out,
            contacts_this_window=row.contacts_this_window,
            provenance=DataProvenance(row.provenance),
        )

    def all(self) -> list[Customer]:
        return [self.get(row.id) for row in self.session.scalars(select(CustomerRow)).all()]


class SqlCaseRepository:
    def __init__(self, session) -> None:
        self.session = session

    def add(self, case: RecoveryCase) -> RecoveryCase:
        event = self.session.get(EventRow, case.event.id) or EventRow(id=case.event.id)
        event.customer_id = case.event.customer_id
        event.event_type = str(case.event.event_type)
        event.amount_paise = case.event.amount.paise
        event.currency = case.event.amount.currency
        event.reason = str(case.event.reason)
        event.occurred_at = case.event.occurred_at
        event.provenance = str(case.event.provenance)
        event.external_ref = case.event.external_ref
        event.metadata_json = json.dumps(case.event.metadata, sort_keys=True)
        self.session.add(event)

        evidence_id = None
        if case.evidence is not None:
            evidence_id = _evidence_id(case.evidence.external_payment_id)
            evidence = self.session.get(EvidenceRow, evidence_id) or EvidenceRow(id=evidence_id)
            evidence.external_payment_id = case.evidence.external_payment_id
            evidence.external_event_id = case.evidence.external_event_id
            evidence.amount_paise = case.evidence.amount.paise
            evidence.captured = case.evidence.captured
            evidence.raw_event_type = case.evidence.raw_event_type
            evidence.verified_at = case.evidence.verified_at
            self.session.add(evidence)

        row = self.session.get(CaseRow, case.id) or CaseRow(id=case.id)
        row.customer_id = case.customer_id
        row.risk_event_id = case.event.id
        row.state = str(case.state)
        row.revenue_at_risk_paise = case.revenue_at_risk.paise
        row.recovered_amount_paise = case.recovered_amount.paise if case.recovered_amount else None
        row.payment_evidence_id = evidence_id
        row.attempts = case.attempts
        row.contacts_made = case.contacts_made
        row.external_link_id = case.external_link_id
        row.recovery_probability = (
            case.diagnosis.recovery_probability if case.diagnosis else None
        )
        row.provenance = str(case.provenance)
        row.dataset_run_id = case.dataset_run_id
        row.diagnosis_json = json.dumps(_diagnosis_out(case.diagnosis)) if case.diagnosis else None
        row.plan_json = json.dumps(_plan_out(case.plan)) if case.plan else None
        self.session.add(row)
        return case

    def get(self, case_id: str) -> RecoveryCase | None:
        row = self.session.get(CaseRow, case_id)
        if row is None:
            return None
        event = self.session.get(EventRow, row.risk_event_id)
        if event is None:
            raise RuntimeError(f"case {case_id} references missing risk event")
        diagnosis = _diagnosis_in(row.diagnosis_json)
        plan = _plan_in(row.plan_json)
        evidence = self.session.get(EvidenceRow, row.payment_evidence_id) if row.payment_evidence_id else None
        return RecoveryCase(
            id=row.id, customer_id=row.customer_id,
            event=RiskEvent(
                id=event.id, customer_id=event.customer_id,
                event_type=RiskEventType(event.event_type), amount=Money(event.amount_paise, event.currency),
                reason=FailureReason(event.reason), occurred_at=_dt(event.occurred_at),
                provenance=DataProvenance(event.provenance), external_ref=event.external_ref,
                metadata=json.loads(event.metadata_json or "{}"),
            ),
            state=CaseState(row.state), attempts=row.attempts, contacts_made=row.contacts_made,
            diagnosis=diagnosis, plan=plan, recovered_amount=Money(row.recovered_amount_paise) if row.recovered_amount_paise else None,
            evidence=(PaymentEvidence(
                external_payment_id=evidence.external_payment_id,
                external_event_id=evidence.external_event_id,
                amount=Money(evidence.amount_paise), captured=evidence.captured,
                verified_at=_dt(evidence.verified_at), raw_event_type=evidence.raw_event_type,
            ) if evidence else None),
            external_link_id=row.external_link_id, dataset_run_id=row.dataset_run_id,
            provenance=DataProvenance(row.provenance), created_at=_dt(row.created_at), updated_at=_dt(row.updated_at),
        )

    def all(self) -> list[RecoveryCase]:
        return [self.get(row.id) for row in self.session.scalars(select(CaseRow)).all()]


class SqlAuditRepository:
    """Idempotent append-only projection of the in-process audit log."""

    def __init__(self, session) -> None:
        self.session = session

    def sync(self, records) -> None:
        for record in records:
            if self.session.get(AuditRow, record.id) is not None:
                continue
            self.session.add(AuditRow(
                id=record.id, case_id=record.case_id, actor=str(record.actor),
                action=record.action, from_state=str(record.from_state) if record.from_state else None,
                to_state=str(record.to_state) if record.to_state else None, detail=record.detail,
                policy_version_id=record.policy_version_id, decision_id=record.decision_id,
                external_event_id=record.external_event_id, at=record.at,
            ))

    def all(self) -> list[AuditRecord]:
        rows = self.session.scalars(select(AuditRow)).all()
        return [AuditRecord(
            id=row.id, case_id=row.case_id, actor=Actor(row.actor), action=row.action,
            from_state=CaseState(row.from_state) if row.from_state else None,
            to_state=CaseState(row.to_state) if row.to_state else None,
            detail=row.detail, at=_dt(row.at), policy_version_id=row.policy_version_id,
            decision_id=row.decision_id, external_event_id=row.external_event_id,
        ) for row in rows]


def _diagnosis_out(value: Diagnosis) -> dict:
    return {
        "cause": str(value.cause),
        "recovery_probability": value.recovery_probability,
        "rationale": value.rationale,
        "produced_by": str(value.produced_by),
        "is_llm_output": value.is_llm_output,
        "confidence": value.confidence,
        "evidence": value.evidence,
        "risk_factors": value.risk_factors,
    }


def _diagnosis_in(raw: str | None) -> Diagnosis | None:
    if not raw:
        return None
    value = json.loads(raw)
    return Diagnosis(
        cause=FailureReason(value["cause"]),
        recovery_probability=value["recovery_probability"],
        rationale=value["rationale"],
        produced_by=Actor(value["produced_by"]),
        is_llm_output=value["is_llm_output"],
        confidence=value.get("confidence", 0.0),
        evidence=value.get("evidence", []),
        risk_factors=value.get("risk_factors", []),
    )


def _plan_out(value: InterventionPlan) -> dict:
    return {
        "intervention": str(value.intervention),
        "discount_percentage": value.discount_percentage,
        "contact_customer": value.contact_customer,
        "rationale": value.rationale,
        "produced_by": str(value.produced_by),
        "is_llm_output": value.is_llm_output,
        "evidence": value.evidence,
        "alternatives_considered": value.alternatives_considered,
        "expected_recovery_value_paise": value.expected_recovery_value.paise if value.expected_recovery_value else None,
        "confidence": value.confidence,
    }


def _plan_in(raw: str | None) -> InterventionPlan | None:
    if not raw:
        return None
    value = json.loads(raw)
    expected = value.get("expected_recovery_value_paise")
    return InterventionPlan(
        intervention=InterventionType(value["intervention"]),
        discount_percentage=value["discount_percentage"],
        contact_customer=value["contact_customer"],
        rationale=value["rationale"],
        produced_by=Actor(value["produced_by"]),
        is_llm_output=value["is_llm_output"],
        evidence=value.get("evidence", []),
        alternatives_considered=value.get("alternatives_considered", []),
        expected_recovery_value=Money(int(expected)) if expected is not None else None,
        confidence=value.get("confidence", 0.0),
    )


def _evidence_id(payment_id: str) -> str:
    return f"evidence_{payment_id}"[:64]

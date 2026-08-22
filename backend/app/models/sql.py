"""Relational schema.

Design notes that matter:

- All money is BIGINT paise. There is no DECIMAL and no FLOAT anywhere near an
  amount.
- audit_records is append-only by convention and by grant: the application role
  is granted INSERT and SELECT only (see the initial migration).
- webhook_events has a UNIQUE constraint on the provider event id, so replay
  protection survives a process restart, unlike an in-memory set.
- recovery_cases.recovered_amount_paise is NULL unless payment_evidence_id is
  set, enforced by a CHECK constraint. Invariant 1 is therefore also a database
  constraint, not only application logic.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    contact: Mapped[str] = mapped_column(String(32), nullable=False)
    lifetime_value_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contacts_this_window: Mapped[int] = mapped_column(Integer, default=0)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("lifetime_value_paise >= 0", name="ck_customer_ltv_non_negative"),
        Index("ix_customers_opted_out", "opted_out"),
    )


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customers.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    reason: Mapped[str] = mapped_column(String(48), nullable=False)
    occurred_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_risk_event_amount_positive"),
        Index("ix_risk_events_customer", "customer_id"),
        Index("ix_risk_events_occurred_at", "occurred_at"),
    )


class PaymentEvidence(Base):
    """Proof that money moved. Written only by the Outcome Verifier."""

    __tablename__ = "payment_evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    external_payment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    captured: Mapped[bool] = mapped_column(Boolean, nullable=False)
    raw_event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("external_payment_id", name="uq_evidence_payment_id"),
        # Uncaptured evidence must never be stored as proof of recovery.
        CheckConstraint("captured = true", name="ck_evidence_must_be_captured"),
    )


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customers.id"), nullable=False
    )
    risk_event_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("risk_events.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    revenue_at_risk_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recovered_amount_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    payment_evidence_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("payment_evidence.id"), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    contacts_made: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    external_link_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recovery_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    diagnosis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("risk_event_id", name="uq_case_per_risk_event"),
        CheckConstraint(
            "revenue_at_risk_paise > 0", name="ck_case_revenue_positive"
        ),
        # Invariant 1 as a database constraint: a recovered amount cannot exist
        # without linked payment evidence, and vice versa.
        CheckConstraint(
            "(recovered_amount_paise IS NULL AND payment_evidence_id IS NULL) "
            "OR (recovered_amount_paise IS NOT NULL AND payment_evidence_id IS NOT NULL)",
            name="ck_recovery_requires_evidence",
        ),
        CheckConstraint(
            "state <> 'RECOVERED' OR payment_evidence_id IS NOT NULL",
            name="ck_recovered_state_requires_evidence",
        ),
        Index("ix_cases_state", "state"),
        Index("ix_cases_customer", "customer_id"),
        Index("ix_cases_link", "external_link_id"),
    )


class PolicyDecisionRecord(Base):
    __tablename__ = "policy_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("recovery_cases.id"), nullable=False
    )
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    policy_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_ids: Mapped[str] = mapped_column(Text, nullable=False)
    reasons: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_decisions_case", "case_id"),)


class AuditRecord(Base):
    """Append-only. No UPDATE or DELETE grant is issued for this table."""

    __tablename__ = "audit_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_audit_case", "case_id"),
        Index("ix_audit_at", "at"),
        Index("ix_audit_action", "action"),
    )


class WebhookEvent(Base):
    """Durable replay protection."""

    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    external_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("external_event_id", name="uq_webhook_event_id"),
    )

"""Core domain entities as plain dataclasses.

No ORM, no framework. The persistence layer maps onto these; they do not know
that persistence exists.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from app.domain.money import Money
from app.domain.states import Actor, CaseState


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class DataProvenance(StrEnum):
    """Anti-fabrication control: every record declares its origin.

    Mixing synthetic benchmark data with live test-mode data would make the
    headline recovery number meaningless, so provenance is mandatory and is
    surfaced in the UI and in every report.
    """

    LIVE_TEST_MODE = "LIVE_TEST_MODE"
    SYNTHETIC = "SYNTHETIC"


class FailureReason(StrEnum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    CARD_EXPIRED = "CARD_EXPIRED"
    CARD_DECLINED = "CARD_DECLINED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    TECHNICAL_ERROR = "TECHNICAL_ERROR"
    ABANDONED_CHECKOUT = "ABANDONED_CHECKOUT"
    INVOICE_UNPAID = "INVOICE_UNPAID"
    UNKNOWN = "UNKNOWN"


class InterventionType(StrEnum):
    PAYMENT_LINK = "PAYMENT_LINK"
    SUBSCRIPTION_RECOVERY = "SUBSCRIPTION_RECOVERY"
    REMINDER = "REMINDER"
    ESCALATION = "ESCALATION"
    STOP = "STOP"


class RiskEventType(StrEnum):
    PAYMENT_FAILED = "PAYMENT_FAILED"
    CHECKOUT_ABANDONED = "CHECKOUT_ABANDONED"
    INVOICE_OVERDUE = "INVOICE_OVERDUE"
    SUBSCRIPTION_HALTED = "SUBSCRIPTION_HALTED"


@dataclass
class Customer:
    id: str
    name: str
    email: str
    contact: str
    lifetime_value: Money
    opted_out: bool = False
    contacts_this_window: int = 0
    provenance: DataProvenance = DataProvenance.SYNTHETIC


@dataclass
class RiskEvent:
    """A single piece of evidence that revenue is at risk."""

    id: str
    customer_id: str
    event_type: RiskEventType
    amount: Money
    reason: FailureReason
    occurred_at: datetime
    provenance: DataProvenance = DataProvenance.SYNTHETIC
    external_ref: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Diagnosis:
    cause: FailureReason
    recovery_probability: float
    rationale: str
    produced_by: Actor
    is_llm_output: bool
    confidence: float = 0.0


@dataclass
class InterventionPlan:
    intervention: InterventionType
    discount_percentage: float
    contact_customer: bool
    rationale: str
    produced_by: Actor
    is_llm_output: bool


@dataclass
class PaymentEvidence:
    """Proof from the provider that money actually moved.

    `captured` is deliberately distinct from `authorized`: an authorized but
    uncaptured payment is not recovered revenue, and conflating the two is the
    single easiest way to report a fake recovery number.
    """

    external_payment_id: str
    external_event_id: str
    amount: Money
    captured: bool
    verified_at: datetime
    raw_event_type: str


@dataclass
class AuditRecord:
    id: str
    case_id: str
    actor: Actor
    action: str
    from_state: CaseState | None
    to_state: CaseState | None
    detail: str
    at: datetime
    policy_version_id: str | None = None
    decision_id: str | None = None
    external_event_id: str | None = None

    def render(self) -> str:
        """One-line human-readable form, for CLI output and log inspection.

        Deliberately includes the authorization references: an audit line that
        does not say which policy version and decision permitted the action is
        not an audit line.
        """
        transition = (
            f"{self.from_state} -> {self.to_state}"
            if self.from_state and self.to_state
            else (str(self.to_state) if self.to_state else "-")
        )
        refs = []
        if self.policy_version_id:
            refs.append(f"policy={self.policy_version_id}")
        if self.decision_id:
            refs.append(f"decision={self.decision_id}")
        if self.external_event_id:
            refs.append(f"event={self.external_event_id}")
        suffix = f"  [{' '.join(refs)}]" if refs else ""
        return (
            f"{self.at.strftime('%H:%M:%S')}  {str(self.actor):<18} "
            f"{self.action:<22} {transition:<34} {self.detail}{suffix}"
        )


@dataclass
class RecoveryCase:
    """Aggregate root. All mutation goes through the state machine service."""

    id: str
    customer_id: str
    event: RiskEvent
    state: CaseState = CaseState.DETECTED
    attempts: int = 0
    contacts_made: int = 0
    diagnosis: Diagnosis | None = None
    plan: InterventionPlan | None = None
    evidence: PaymentEvidence | None = None
    recovered_amount: Money | None = None
    external_link_id: str | None = None
    dataset_run_id: str | None = None
    provenance: DataProvenance = DataProvenance.SYNTHETIC
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    @property
    def revenue_at_risk(self) -> Money:
        return self.event.amount

    @property
    def expected_recoverable_value(self) -> Money:
        if self.diagnosis is None:
            return Money(0)
        return self.revenue_at_risk.scaled(self.diagnosis.recovery_probability)

    @property
    def is_terminal(self) -> bool:
        from app.domain.states import TERMINAL_STATES

        return self.state in TERMINAL_STATES

"""Outcome Verifier: the sole authority on whether money was recovered.

Invariant 1 is enforced here and in the state machine's actor restrictions. A
case reaches RECOVERED only when a provider event proves a captured payment.
An authorized-but-uncaptured payment is explicitly not a recovery.
"""

from __future__ import annotations

from app.domain.entities import PaymentEvidence, RecoveryCase, utcnow
from app.domain.errors import InvariantViolation
from app.domain.money import Money
from app.domain.states import Actor, CaseState
from app.services.audit import AuditLog
from app.services.state_machine import StateMachine

CAPTURED_EVENTS = frozenset({"payment_link.paid", "payment.captured"})
FAILED_EVENTS = frozenset({"payment.failed", "payment_link.expired"})
# Present for completeness and deliberately NOT treated as recovery.
AUTHORIZED_ONLY_EVENTS = frozenset({"payment.authorized"})


class OutcomeVerifier:
    actor = Actor.OUTCOME_VERIFIER

    def __init__(self, state_machine: StateMachine, audit: AuditLog) -> None:
        self.sm = state_machine
        self.audit = audit

    def verify(
        self,
        case: RecoveryCase,
        event_type: str,
        external_event_id: str,
        payment_id: str,
        amount_paise: int,
        captured: bool,
    ) -> RecoveryCase:
        if event_type in AUTHORIZED_ONLY_EVENTS or (
            event_type in CAPTURED_EVENTS and not captured
        ):
            self.audit.record(
                case_id=case.id,
                actor=self.actor,
                action="EVIDENCE_INSUFFICIENT",
                detail=(
                    f"{event_type} does not prove capture; case remains {case.state}"
                ),
                external_event_id=external_event_id,
            )
            return case

        if event_type in CAPTURED_EVENTS:
            if case.state is not CaseState.AWAITING_PAYMENT:
                raise InvariantViolation(
                    f"capture evidence for case {case.id} in unexpected state {case.state}"
                )
            case.evidence = PaymentEvidence(
                external_payment_id=payment_id,
                external_event_id=external_event_id,
                amount=Money(int(amount_paise)),
                captured=True,
                verified_at=utcnow(),
                raw_event_type=event_type,
            )
            case.recovered_amount = case.evidence.amount
            self.sm.transition(
                case,
                CaseState.RECOVERED,
                self.actor,
                detail=f"verified capture of {case.evidence.amount} via {event_type}",
                external_event_id=external_event_id,
            )
            return case

        if event_type in FAILED_EVENTS:
            if case.state is CaseState.AWAITING_PAYMENT:
                self.sm.transition(
                    case,
                    CaseState.FAILED,
                    self.actor,
                    detail=f"{event_type} received",
                    external_event_id=external_event_id,
                )
            return case

        self.audit.record(
            case_id=case.id,
            actor=self.actor,
            action="EVENT_IGNORED",
            detail=f"unhandled event type {event_type}",
            external_event_id=external_event_id,
        )
        return case

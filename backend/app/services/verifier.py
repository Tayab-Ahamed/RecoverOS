"""Outcome Verifier: the sole authority on whether money was recovered.

Invariant 1 is enforced here and in the state machine's actor restrictions. A
case reaches RECOVERED only when a provider event proves a captured payment.
An authorized-but-uncaptured payment is explicitly not a recovery.
"""

from __future__ import annotations

from app.domain.entities import PaymentEvidence, RecoveryCase, utcnow
from app.domain.errors import InvariantViolation
from app.domain.money import Money
from app.domain.states import Actor, CaseState, PromiseStatus
from app.integrations.razorpay_catalog import (
    all_confirming_events,
    all_failing_events,
)
from app.services.audit import AuditLog
from app.services.state_machine import StateMachine

# Derived from the Razorpay product catalogue rather than hand-listed, so
# adding a product cannot silently leave its proof-of-payment event
# unrecognised. See app/integrations/razorpay_catalog.py.
CAPTURED_EVENTS = all_confirming_events()
FAILED_EVENTS = all_failing_events()
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

            # Strict Promise-to-Pay fulfillment matching: exact case reference AND exact amount.
            if case.promise_to_pay is not None and case.promise_to_pay.status is PromiseStatus.PENDING:
                if case.evidence.amount == case.promise_to_pay.amount:
                    case.promise_to_pay.status = PromiseStatus.FULFILLED
                    case.promise_to_pay.fulfilled_at = case.evidence.verified_at
                    case.promise_to_pay.fulfilled_evidence_id = case.evidence.external_payment_id
                    self.audit.record(
                        case_id=case.id,
                        actor=self.actor,
                        action="PTP_FULFILLED",
                        detail=(
                            f"promise {case.promise_to_pay.id} fulfilled by verified capture of "
                            f"{case.evidence.amount} (payment={payment_id})"
                        ),
                        external_event_id=external_event_id,
                    )
                else:
                    self.audit.record(
                        case_id=case.id,
                        actor=self.actor,
                        action="PTP_PARTIAL_PAYMENT",
                        detail=(
                            f"captured {case.evidence.amount} does not match promised "
                            f"{case.promise_to_pay.amount}; promise {case.promise_to_pay.id} remains PENDING"
                        ),
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

"""The only component permitted to take an outbound action.

Authorization is enforced by the signature: `execute` requires a Decision, and
refuses to act unless it is affirmative and matches the case. There is no code
path from an agent to a provider that does not pass through here.
"""

from __future__ import annotations

from app.domain.entities import (
    Customer,
    InterventionPlan,
    InterventionType,
    RecoveryCase,
)
from app.domain.errors import PolicyViolation
from app.domain.states import Actor, CaseState
from app.integrations.provider import (
    PaymentLinkRequest,
    PaymentProvider,
    ProviderError,
)
from app.policies.engine import Decision
from app.services.audit import AuditLog
from app.services.state_machine import StateMachine


class RecoveryExecutor:
    def __init__(
        self,
        provider: PaymentProvider,
        state_machine: StateMachine,
        audit: AuditLog,
    ) -> None:
        self.provider = provider
        self.sm = state_machine
        self.audit = audit

    def execute(
        self,
        case: RecoveryCase,
        plan: InterventionPlan,
        customer: Customer,
        decision: Decision,
    ) -> RecoveryCase:
        # Invariant 2: no action without authorization.
        if not decision.allowed:
            raise PolicyViolation(
                f"executor refused: decision {decision.id} is a denial ({decision.summary})"
            )
        if decision.requires_human_approval and case.state is not CaseState.APPROVED:
            raise PolicyViolation(
                f"executor refused: decision {decision.id} needs human approval and "
                f"case is in {case.state}"
            )
        if case.state is not CaseState.APPROVED:
            raise PolicyViolation(
                f"executor refused: case {case.id} must be APPROVED, is {case.state}"
            )

        if plan.intervention is InterventionType.STOP:
            self.audit.record(
                case_id=case.id,
                actor=Actor.EXECUTOR,
                action="NO_OP",
                detail="stop plan requires no outbound action",
                decision_id=decision.id,
                policy_version_id=decision.policy_version_id,
            )
            return case

        self.sm.transition(
            case,
            CaseState.EXECUTING,
            Actor.EXECUTOR,
            detail=f"executing {plan.intervention}",
            decision_id=decision.id,
            policy_version_id=decision.policy_version_id,
        )

        amount = case.revenue_at_risk
        if plan.discount_percentage:
            amount = amount - amount.percent(plan.discount_percentage)

        req = PaymentLinkRequest(
            amount=amount,
            reference_id=case.id,
            description=f"Recovery for {case.event.reason} ({case.event.id})",
            customer_name=customer.name,
            customer_email=customer.email,
            customer_contact=customer.contact,
            notify_email=True,
            notify_sms=False,
            reminder_enable=True,
            notes={
                "case_id": case.id,
                "intervention": str(plan.intervention),
                "policy_version": decision.policy_version_id,
                "decision_id": decision.id,
            },
        )

        try:
            link = self.provider.create_payment_link(req)
        except ProviderError as exc:
            self.audit.record(
                case_id=case.id,
                actor=Actor.EXECUTOR,
                action="PROVIDER_ERROR",
                detail=str(exc),
                decision_id=decision.id,
                policy_version_id=decision.policy_version_id,
            )
            case.attempts += 1
            self.sm.transition(
                case,
                CaseState.FAILED,
                Actor.EXECUTOR,
                detail=f"provider error: {exc}",
                decision_id=decision.id,
                policy_version_id=decision.policy_version_id,
            )
            return case

        case.attempts += 1
        if plan.contact_customer:
            case.contacts_made += 1
            customer.contacts_this_window += 1
        case.external_link_id = link.id

        self.audit.record(
            case_id=case.id,
            actor=Actor.EXECUTOR,
            action="PAYMENT_LINK_CREATED",
            detail=f"{link.id} for {amount} via {self.provider.name}",
            decision_id=decision.id,
            policy_version_id=decision.policy_version_id,
        )

        self.sm.transition(
            case,
            CaseState.AWAITING_PAYMENT,
            Actor.EXECUTOR,
            detail=f"awaiting payment on {link.id}",
            decision_id=decision.id,
            policy_version_id=decision.policy_version_id,
        )
        return case

"""Human approval of a held case.

Approval is a separate service rather than a branch inside the orchestrator,
because it is a different trust boundary: it is the one place where a human
decision enters the loop. Policy is re-evaluated at approval time, so a stale
approval cannot authorize an action that policy would now refuse.
"""

from __future__ import annotations

from app.domain.entities import Customer, RecoveryCase
from app.domain.errors import IllegalTransition
from app.domain.states import Actor, CaseState
from app.policies.engine import PolicyEngine
from app.services.audit import AuditLog
from app.services.executor import RecoveryExecutor
from app.services.state_machine import StateMachine


class ApprovalService:
    def __init__(
        self,
        policy: PolicyEngine,
        executor: RecoveryExecutor,
        state_machine: StateMachine,
        audit: AuditLog,
    ) -> None:
        self.policy = policy
        self.executor = executor
        self.sm = state_machine
        self.audit = audit

    def approve(
        self, case: RecoveryCase, customer: Customer, approver: str
    ) -> RecoveryCase:
        if case.state is not CaseState.AWAITING_APPROVAL:
            raise IllegalTransition(
                f"case {case.id} is {case.state}, not awaiting approval"
            )
        assert case.plan is not None

        # Re-authorize: conditions may have changed since the case was held.
        decision = self.policy.authorize(case, case.plan, customer)
        self.audit.record(
            case_id=case.id,
            actor=Actor.POLICY_ENGINE,
            action="POLICY_REVALIDATION",
            detail=decision.summary,
            policy_version_id=decision.policy_version_id,
            decision_id=decision.id,
        )
        if not decision.allowed:
            self.sm.transition(
                case,
                CaseState.DENIED,
                Actor.POLICY_ENGINE,
                detail=f"revalidation failed at approval time: {decision.summary}",
                decision_id=decision.id,
            )
            self.sm.transition(
                case, CaseState.STOPPED, Actor.SYSTEM, detail="stopped after denial"
            )
            return case

        self.sm.transition(
            case,
            CaseState.APPROVED,
            Actor.HUMAN,
            detail=f"approved by {approver}",
            decision_id=decision.id,
            policy_version_id=decision.policy_version_id,
        )
        self.executor.execute(case, case.plan, customer, decision)
        return case

    def deny(self, case: RecoveryCase, approver: str, reason: str) -> RecoveryCase:
        if case.state is not CaseState.AWAITING_APPROVAL:
            raise IllegalTransition(
                f"case {case.id} is {case.state}, not awaiting approval"
            )
        self.sm.transition(
            case,
            CaseState.DENIED,
            Actor.HUMAN,
            detail=f"rejected by {approver}: {reason}",
        )
        self.sm.transition(
            case, CaseState.STOPPED, Actor.SYSTEM, detail="stopped after human rejection"
        )
        return case

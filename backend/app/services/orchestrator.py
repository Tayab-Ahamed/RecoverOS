"""The recovery loop.

DETECT -> DIAGNOSE -> DECIDE -> GOVERN -> ACT -> VERIFY -> RECOVER / STOP /
RETRY / ESCALATE.

The loop executes; it does not recommend. Every step is explicit here so the
ordering of authorization relative to action is readable in one place.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.agents.diagnosis_agent import DiagnosisAgent
from app.agents.strategist_agent import StrategistAgent
from app.detection.rules import RiskSignal
from app.domain.entities import (
    Customer,
    DataProvenance,
    InterventionType,
    Money,
    PromiseToPay,
    RecoveryCase,
    new_id,
)
from app.domain.errors import PolicyViolation
from app.domain.states import Actor, CaseState, PromiseStatus
from app.policies.engine import Decision, PolicyEngine
from app.services.audit import AuditLog
from app.services.executor import RecoveryExecutor
from app.services.state_machine import StateMachine


class RecoveryOrchestrator:
    def __init__(
        self,
        policy: PolicyEngine,
        executor: RecoveryExecutor,
        state_machine: StateMachine,
        audit: AuditLog,
        diagnosis_agent: DiagnosisAgent | None = None,
        strategist: StrategistAgent | None = None,
        approver: Callable[[RecoveryCase, Decision], bool] | None = None,
    ) -> None:
        self.policy = policy
        self.executor = executor
        self.sm = state_machine
        self.audit = audit
        self.diagnosis_agent = diagnosis_agent or DiagnosisAgent()
        self.strategist = strategist or StrategistAgent()
        # If no approver is supplied, high-value cases stop at AWAITING_APPROVAL
        # and wait for a human. Silently self-approving would defeat the control.
        self.approver = approver

    def open_case(
        self,
        signal: RiskSignal,
        provenance: DataProvenance = DataProvenance.SYNTHETIC,
        dataset_run_id: str | None = None,
    ) -> RecoveryCase:
        case = RecoveryCase(
            id=new_id("case"),
            customer_id=signal.event.customer_id,
            event=signal.event,
            provenance=provenance,
            dataset_run_id=dataset_run_id,
        )
        self.audit.record(
            case_id=case.id,
            actor=Actor.REVENUE_SENTINEL,
            action="CASE_OPENED",
            detail=(
                f"revenue at risk {signal.revenue_at_risk}, "
                f"priority {signal.priority}"
            ),
            to_state=CaseState.DETECTED,
        )
        return case

    def advance(self, case: RecoveryCase, customer: Customer) -> RecoveryCase:
        """Drive a case from DETECTED to either an outbound action or a stop."""
        # ---- DIAGNOSE ----
        self.sm.transition(case, CaseState.DIAGNOSING, Actor.SYSTEM)
        case.diagnosis = self.diagnosis_agent.diagnose(case.event, customer)
        self.audit.record(
            case_id=case.id,
            actor=Actor.DIAGNOSIS_AGENT,
            action="DIAGNOSED",
            detail=(
                f"cause={case.diagnosis.cause} "
                f"p={case.diagnosis.recovery_probability} "
                f"llm={case.diagnosis.is_llm_output}"
            ),
        )

        if customer.opted_out or case.diagnosis.recovery_probability <= 0.0:
            self.sm.transition(
                case,
                CaseState.INELIGIBLE,
                Actor.SYSTEM,
                detail="opted out or zero recovery probability",
            )
            return case

        # State transition: if an outstanding promise has elapsed without capture, mark BROKEN.
        if case.promise_to_pay is not None and case.promise_to_pay.status is PromiseStatus.PENDING:
            current_time = self.policy._clock()
            if current_time >= case.promise_to_pay.promise_due_date:
                case.promise_to_pay.status = PromiseStatus.BROKEN
                case.broken_promises_count += 1
                self.audit.record(
                    case_id=case.id,
                    actor=Actor.SYSTEM,
                    action="PTP_BROKEN",
                    detail=(
                        f"promise {case.promise_to_pay.id} expired at "
                        f"{case.promise_to_pay.promise_due_date.strftime('%Y-%m-%d %H:%M:%S UTC')} "
                        f"without verified capture"
                    ),
                )

        self.sm.transition(case, CaseState.ELIGIBLE, Actor.SYSTEM)
        return self._plan_and_act(case, customer)

    def _plan_and_act(self, case: RecoveryCase, customer: Customer) -> RecoveryCase:
        # ---- DECIDE (propose) ----
        assert case.diagnosis is not None
        case.plan = self.strategist.plan(case, case.diagnosis, customer)
        self.sm.transition(
            case,
            CaseState.PLANNED,
            Actor.STRATEGIST_AGENT,
            detail=f"proposed {case.plan.intervention}",
        )

        # ---- GOVERN ----
        self.sm.transition(case, CaseState.POLICY_CHECK, Actor.SYSTEM)
        decision = self.policy.authorize(case, case.plan, customer)
        self.audit.record(
            case_id=case.id,
            actor=Actor.POLICY_ENGINE,
            action="POLICY_DECISION",
            detail=decision.summary,
            policy_version_id=decision.policy_version_id,
            decision_id=decision.id,
        )

        if not decision.allowed:
            self.sm.transition(
                case,
                CaseState.DENIED,
                Actor.POLICY_ENGINE,
                detail=decision.summary,
                policy_version_id=decision.policy_version_id,
                decision_id=decision.id,
            )
            # A denial after one or more attempts means money is still
            # outstanding, so the case is escalated to a human. A denial before
            # any attempt (opt-out, below the economic floor) is a clean stop.
            if case.attempts >= 1:
                self.sm.transition(
                    case,
                    CaseState.ESCALATED,
                    Actor.SYSTEM,
                    detail="policy stopped further attempts; handed to a human",
                    decision_id=decision.id,
                )
            else:
                self.sm.transition(
                    case,
                    CaseState.STOPPED,
                    Actor.SYSTEM,
                    detail="stopped after policy denial",
                    decision_id=decision.id,
                )
            return case

        if decision.requires_human_approval:
            self.sm.transition(
                case,
                CaseState.AWAITING_APPROVAL,
                Actor.POLICY_ENGINE,
                detail="value at or above manual review threshold",
                policy_version_id=decision.policy_version_id,
                decision_id=decision.id,
            )
            if self.approver is None:
                return case
            if not self.approver(case, decision):
                self.sm.transition(
                    case,
                    CaseState.DENIED,
                    Actor.HUMAN,
                    detail="human rejected",
                    decision_id=decision.id,
                )
                self.sm.transition(
                    case, CaseState.STOPPED, Actor.SYSTEM, detail="stopped after rejection"
                )
                return case
            self.sm.transition(
                case,
                CaseState.APPROVED,
                Actor.HUMAN,
                detail="human approved",
                decision_id=decision.id,
                policy_version_id=decision.policy_version_id,
            )
        else:
            self.sm.transition(
                case,
                CaseState.APPROVED,
                Actor.POLICY_ENGINE,
                detail=decision.summary,
                decision_id=decision.id,
                policy_version_id=decision.policy_version_id,
            )

        # ---- ACT ----
        if case.plan.intervention is InterventionType.STOP:
            self.executor.execute(case, case.plan, customer, decision)
            self.sm.transition(
                case, CaseState.STOPPED, Actor.SYSTEM, detail="no action required"
            )
            return case

        try:
            self.executor.execute(case, case.plan, customer, decision)
        except PolicyViolation:
            # An executor refusal is a bug or an attack, never routine. It is
            # recorded and re-raised so a run fails loudly.
            self.audit.record(
                case_id=case.id,
                actor=Actor.EXECUTOR,
                action="REFUSED",
                detail="executor refused an unauthorized action",
                decision_id=decision.id,
            )
            raise
        return case

    def handle_failure(self, case: RecoveryCase, customer: Customer) -> RecoveryCase:
        """Apply stopping rules after a failed attempt."""
        if case.state is not CaseState.FAILED:
            return case

        if case.attempts >= self.policy.rules.max_recovery_attempts:
            self.sm.transition(
                case,
                CaseState.MAX_ATTEMPTS,
                Actor.SYSTEM,
                detail=f"attempts exhausted at {case.attempts}",
            )
            self.sm.transition(
                case,
                CaseState.ESCALATED,
                Actor.SYSTEM,
                detail="escalated to human collections queue",
            )
            return case

        self.sm.transition(
            case,
            CaseState.RETRY_ELIGIBLE,
            Actor.SYSTEM,
            detail=f"attempt {case.attempts} failed; retry permitted",
        )
        return self._plan_and_act(case, customer)

    def record_promise_to_pay(
        self,
        case: RecoveryCase,
        amount: Money,
        promise_due_date: datetime,
        customer: Customer | None = None,
        notes: str = "",
        actor: Actor = Actor.HUMAN,
    ) -> PromiseToPay:
        """Register an inbound customer promise to pay.

        Enforces timezone awareness, horizon cap, and consecutive broken limits.
        Emits PTP_RECORDED audit record upon registration.
        """
        if promise_due_date.tzinfo is None:
            raise ValueError("promise_due_date must be timezone-aware (e.g. UTC or with tzinfo)")

        now = self.policy._clock()
        if promise_due_date <= now:
            raise ValueError("promise_due_date must be in the future")

        horizon_days = (promise_due_date - now).total_seconds() / 86400.0
        if horizon_days > self.policy.rules.max_promise_horizon_days:
            raise ValueError(
                f"promise horizon {horizon_days:.1f} days exceeds policy cap of "
                f"{self.policy.rules.max_promise_horizon_days} days"
            )

        if case.broken_promises_count >= self.policy.rules.max_broken_promises_per_case:
            raise ValueError(
                f"case has {case.broken_promises_count} broken promises; policy limit is "
                f"{self.policy.rules.max_broken_promises_per_case}. Further grace refused."
            )

        ptp = PromiseToPay(
            id=new_id("ptp"),
            case_id=case.id,
            customer_id=case.customer_id,
            amount=amount,
            promised_at=now,
            promise_due_date=promise_due_date,
            status=PromiseStatus.PENDING,
            notes=notes,
        )
        case.promise_to_pay = ptp

        self.audit.record(
            case_id=case.id,
            actor=actor,
            action="PTP_RECORDED",
            detail=(
                f"promise {ptp.id} recorded for Rs {amount.rupees_str} due "
                f"{promise_due_date.strftime('%Y-%m-%d %H:%M:%S %Z')} (horizon {horizon_days:.1f}d)"
            ),
        )
        return ptp

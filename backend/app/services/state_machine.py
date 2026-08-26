"""Guarded state transitions.

Every state change in the system goes through `transition`. It enforces the
transition table, the per-state actor restrictions, and the audit requirement
together, so none of the three can be forgotten at a call site.
"""

from __future__ import annotations

from app.domain.entities import RecoveryCase, utcnow
from app.domain.errors import IllegalTransition, UnauthorizedActor
from app.domain.states import Actor, CaseState, is_transition_allowed, may_actor_write
from app.services.audit import AuditLog


class StateMachine:
    def __init__(self, audit: AuditLog) -> None:
        self.audit = audit

    def transition(
        self,
        case: RecoveryCase,
        to: CaseState,
        actor: Actor,
        detail: str = "",
        policy_version_id: str | None = None,
        decision_id: str | None = None,
        external_event_id: str | None = None,
    ) -> RecoveryCase:
        src = case.state

        if not is_transition_allowed(src, to):
            raise IllegalTransition(
                f"{src} -> {to} is not a legal transition for case {case.id}"
            )

        if not may_actor_write(to, actor):
            raise UnauthorizedActor(
                f"actor {actor} may not move case {case.id} into {to}"
            )

        case.state = to
        case.updated_at = utcnow()

        self.audit.record(
            case_id=case.id,
            actor=actor,
            action="STATE_TRANSITION",
            detail=detail or f"{src} -> {to}",
            from_state=src,
            to_state=to,
            policy_version_id=policy_version_id,
            decision_id=decision_id,
            external_event_id=external_event_id,
        )
        return case

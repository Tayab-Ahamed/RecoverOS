"""The single canonical case state enum and its legal transitions.

Contradiction C2 in the Phase 0 audit was two competing state lists across
specification pages. This module is the only definition; anything else is a
bug. The transition table is data, not scattered if-statements, so that the
reachable state graph can be asserted in tests.
"""

from __future__ import annotations

from enum import StrEnum


class CaseState(StrEnum):
    DETECTED = "DETECTED"
    DIAGNOSING = "DIAGNOSING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    PLANNED = "PLANNED"
    POLICY_CHECK = "POLICY_CHECK"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXECUTING = "EXECUTING"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    RECOVERED = "RECOVERED"
    FAILED = "FAILED"
    RETRY_ELIGIBLE = "RETRY_ELIGIBLE"
    MAX_ATTEMPTS = "MAX_ATTEMPTS"
    ESCALATED = "ESCALATED"
    STOPPED = "STOPPED"


class Actor(StrEnum):
    SYSTEM = "SYSTEM"
    REVENUE_SENTINEL = "REVENUE_SENTINEL"
    DIAGNOSIS_AGENT = "DIAGNOSIS_AGENT"
    STRATEGIST_AGENT = "STRATEGIST_AGENT"
    POLICY_ENGINE = "POLICY_ENGINE"
    EXECUTOR = "EXECUTOR"
    OUTCOME_VERIFIER = "OUTCOME_VERIFIER"
    WEBHOOK = "WEBHOOK"
    HUMAN = "HUMAN"


TERMINAL_STATES: frozenset[CaseState] = frozenset(
    {
        CaseState.RECOVERED,
        CaseState.STOPPED,
        CaseState.ESCALATED,
        CaseState.INELIGIBLE,
    }
)

# Invariant 1: only the Outcome Verifier may declare money recovered.
# The verifier is the only component that reads payment evidence, so making it
# the sole writer means an optimistic agent cannot inflate the headline metric.
STATE_WRITE_RESTRICTIONS: dict[CaseState, frozenset[Actor]] = {
    CaseState.RECOVERED: frozenset({Actor.OUTCOME_VERIFIER}),
    CaseState.APPROVED: frozenset({Actor.POLICY_ENGINE, Actor.HUMAN}),
    CaseState.DENIED: frozenset({Actor.POLICY_ENGINE, Actor.HUMAN}),
}

ALLOWED_TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.DETECTED: frozenset({CaseState.DIAGNOSING, CaseState.STOPPED}),
    CaseState.DIAGNOSING: frozenset(
        {CaseState.ELIGIBLE, CaseState.INELIGIBLE, CaseState.STOPPED}
    ),
    CaseState.ELIGIBLE: frozenset({CaseState.PLANNED, CaseState.STOPPED}),
    CaseState.INELIGIBLE: frozenset(),
    CaseState.PLANNED: frozenset({CaseState.POLICY_CHECK, CaseState.STOPPED}),
    CaseState.POLICY_CHECK: frozenset(
        {
            CaseState.APPROVED,
            CaseState.DENIED,
            CaseState.AWAITING_APPROVAL,
            CaseState.STOPPED,
        }
    ),
    CaseState.AWAITING_APPROVAL: frozenset(
        {CaseState.APPROVED, CaseState.DENIED, CaseState.STOPPED}
    ),
    CaseState.APPROVED: frozenset({CaseState.EXECUTING, CaseState.ESCALATED, CaseState.STOPPED}),
    CaseState.DENIED: frozenset({CaseState.STOPPED, CaseState.ESCALATED}),
    CaseState.EXECUTING: frozenset(
        {CaseState.AWAITING_PAYMENT, CaseState.FAILED, CaseState.STOPPED}
    ),
    CaseState.AWAITING_PAYMENT: frozenset(
        {CaseState.RECOVERED, CaseState.FAILED, CaseState.STOPPED}
    ),
    CaseState.RECOVERED: frozenset(),
    CaseState.FAILED: frozenset(
        {CaseState.RETRY_ELIGIBLE, CaseState.MAX_ATTEMPTS, CaseState.STOPPED}
    ),
    CaseState.RETRY_ELIGIBLE: frozenset({CaseState.PLANNED, CaseState.STOPPED}),
    CaseState.MAX_ATTEMPTS: frozenset({CaseState.ESCALATED, CaseState.STOPPED}),
    CaseState.ESCALATED: frozenset(),
    CaseState.STOPPED: frozenset(),
}


def is_transition_allowed(src: CaseState, dst: CaseState) -> bool:
    return dst in ALLOWED_TRANSITIONS.get(src, frozenset())


def may_actor_write(state: CaseState, actor: Actor) -> bool:
    restriction = STATE_WRITE_RESTRICTIONS.get(state)
    return True if restriction is None else actor in restriction

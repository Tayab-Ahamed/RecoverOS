"""Append-only audit log.

Invariant 5 requires an audit record for every financial or recovery state
transition. The store refuses mutation and deletion so that the trail cannot
be quietly rewritten.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.domain.entities import AuditRecord, new_id, utcnow
from app.domain.states import Actor, CaseState


class AuditLog:
    """Append-only trail.

    The clock is injectable for the same reason PolicyEngine's is: a caller that
    pins policy evaluation to a fixed instant must be able to pin the audit
    timestamps to the same instant, or the trail will describe decisions as
    happening at a time the decider never saw. Production passes nothing and
    gets real UTC wall time.
    """

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._records: list[AuditRecord] = []
        self._clock = clock or utcnow

    def record(
        self,
        case_id: str,
        actor: Actor,
        action: str,
        detail: str,
        from_state: CaseState | None = None,
        to_state: CaseState | None = None,
        policy_version_id: str | None = None,
        decision_id: str | None = None,
        external_event_id: str | None = None,
    ) -> AuditRecord:
        rec = AuditRecord(
            id=new_id("aud"),
            case_id=case_id,
            actor=actor,
            action=action,
            from_state=from_state,
            to_state=to_state,
            detail=detail,
            at=self._clock(),
            policy_version_id=policy_version_id,
            decision_id=decision_id,
            external_event_id=external_event_id,
        )
        self._records.append(rec)
        return rec

    def for_case(self, case_id: str) -> list[AuditRecord]:
        return [r for r in self._records if r.case_id == case_id]

    def all(self) -> list[AuditRecord]:
        return list(self._records)

    def load(self, records: list[AuditRecord]) -> None:
        """Hydrate an existing append-only trail during process startup."""
        self._records = list(records)

    def __len__(self) -> int:
        return len(self._records)

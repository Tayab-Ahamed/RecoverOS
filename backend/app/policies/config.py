"""Policy configuration and immutable versioning.

Every decision records the exact policy version that authorized it. Without
this, an audit trail cannot answer "what rules were in force at the time?",
which is the whole point of having an audit trail.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime

from app.domain.entities import utcnow
from app.domain.money import Money


@dataclass(frozen=True)
class PolicyRules:
    max_recovery_attempts: int = 3
    max_customer_contacts: int = 2
    # Stored in paise. Rs 100 = 10000 paise (contradiction C9).
    min_recovery_value_paise: int = 10_000
    max_discount_percentage: float = 10.0
    high_value_manual_review_threshold_paise: int = 5_000_000
    stop_after_success: bool = True
    stop_after_opt_out: bool = True
    require_approval_above_threshold: bool = True
    # Time-of-day contact window (UTC hours, inclusive start, exclusive end).
    # Contacts are blocked outside this window to avoid disturbing customers at
    # night and to meet basic merchant compliance requirements.
    no_contact_before_hour: int = 8   # don't contact before 8 AM UTC
    no_contact_after_hour: int = 21   # don't contact at or after 9 PM UTC

    @property
    def min_recovery_value(self) -> Money:
        return Money(self.min_recovery_value_paise)

    @property
    def high_value_threshold(self) -> Money:
        return Money(self.high_value_manual_review_threshold_paise)


@dataclass(frozen=True)
class PolicyVersion:
    """An append-only, content-addressed snapshot of the rules."""

    id: str
    rules: PolicyRules
    created_at: datetime = field(default_factory=utcnow)

    @property
    def checksum(self) -> str:
        payload = json.dumps(asdict(self.rules), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


DEFAULT_POLICY = PolicyVersion(id="v1", rules=PolicyRules())

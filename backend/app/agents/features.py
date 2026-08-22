"""Observable context for a recovery decision.

This is the agent's entire view of the world. It is built only from the case,
the customer record and the diagnosis -- never from the evaluation world model.
Keeping extraction in one place makes that claim auditable in a single file
rather than spread across every agent.

The segment key is coarse on purpose. A contextual learner needs enough data
per cell to estimate a rate; a key that is unique per case would learn nothing
and would silently degrade into a very slow random policy.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.entities import Customer, Diagnosis, RecoveryCase

AMOUNT_BANDS: tuple[tuple[int, str], ...] = (
    (50_000, "micro"),
    (200_000, "small"),
    (1_000_000, "mid"),
    (5_000_000, "large"),
)

LTV_BANDS: tuple[tuple[int, str], ...] = (
    (500_000, "low"),
    (2_500_000, "medium"),
    (10_000_000, "high"),
)


def amount_band(paise: int) -> str:
    for threshold, label in AMOUNT_BANDS:
        if paise < threshold:
            return label
    return "xlarge"


def ltv_band(paise: int) -> str:
    for threshold, label in LTV_BANDS:
        if paise < threshold:
            return label
    return "vip"


@dataclass(frozen=True)
class CaseFeatures:
    """A flat, hashable description of one decision point."""

    reason: str
    event_type: str
    amount_band: str
    ltv_band: str
    attempt: int
    contacts_made: int
    prior_contacts_in_window: int
    amount_paise: int
    prior_probability: float

    @property
    def segment(self) -> str:
        """The learning cell.

        Attempt index is included because the correct action genuinely changes
        between the first and second try. Customer identity is deliberately
        excluded: per-customer cells would never accumulate enough observations.

        Amount band is deliberately *excluded*, which was not the first design.
        Including it produced 8 reasons x 5 bands x 3 attempts = 120 cells; at
        2000 decisions across 5 arms that is roughly 2 observations per
        (cell, arm), and Thompson sampling in that regime never leaves its
        prior -- measured exploration stayed near 45% and the learner lost to
        the rulebook it was supposed to beat. Dropping the band gives 24 cells
        and ~17 observations per (cell, arm) at the same sample size. Value is
        not lost: the bandit already ranks arms by sampled probability times
        net amount, so amount enters the decision through the objective, and
        the propensity model carries it as a feature. Segment the context by
        what changes the best *action*; let the objective handle magnitude.
        """
        return f"{self.reason}|a{min(self.attempt, 2)}"

    @property
    def fatigued(self) -> bool:
        return self.prior_contacts_in_window >= 2 or self.contacts_made >= 1

    def to_dict(self) -> dict:
        return {
            "reason": self.reason,
            "event_type": self.event_type,
            "amount_band": self.amount_band,
            "ltv_band": self.ltv_band,
            "attempt": self.attempt,
            "contacts_made": self.contacts_made,
            "prior_contacts_in_window": self.prior_contacts_in_window,
            "segment": self.segment,
            "prior_probability": self.prior_probability,
        }

    def vector(self) -> dict[str, float]:
        """Sparse one-hot-plus-scalar encoding for the online propensity model.

        Returned as a name->value mapping rather than a positional list so that
        adding a feature cannot silently shift the meaning of learned weights.
        """
        v: dict[str, float] = {
            "bias": 1.0,
            f"reason={self.reason}": 1.0,
            f"event={self.event_type}": 1.0,
            f"amount={self.amount_band}": 1.0,
            f"ltv={self.ltv_band}": 1.0,
            f"attempt={min(self.attempt, 3)}": 1.0,
            "contacts": float(min(self.contacts_made, 3)),
            "window_contacts": float(min(self.prior_contacts_in_window, 3)),
            "prior": self.prior_probability,
        }
        if self.fatigued:
            v["fatigued"] = 1.0
        return v


def extract(
    case: RecoveryCase,
    diagnosis: Diagnosis,
    customer: Customer,
) -> CaseFeatures:
    return CaseFeatures(
        reason=str(case.event.reason),
        event_type=str(case.event.event_type),
        amount_band=amount_band(case.revenue_at_risk.paise),
        ltv_band=ltv_band(customer.lifetime_value.paise),
        attempt=case.attempts,
        contacts_made=case.contacts_made,
        prior_contacts_in_window=customer.contacts_this_window,
        amount_paise=case.revenue_at_risk.paise,
        prior_probability=diagnosis.recovery_probability,
    )

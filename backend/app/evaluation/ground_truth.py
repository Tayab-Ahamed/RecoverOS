"""The hidden world model. The agent never sees this file's numbers.

Why this exists
---------------
The first version of this benchmark decided whether a customer paid by
sampling against `diagnosis.recovery_probability` -- the agent's *own* belief.
Under that design the agent could not be wrong: its prediction was the ground
truth, so "recovery rate" measured nothing about decision quality, and the
reported lift over a fixed baseline was an artifact of retry branching rather
than evidence of intelligence.

This module fixes that. It defines a conversion process that:

1. Uses base rates that are *deliberately different* from the priors in
   `app/detection/rules.py`, so the agent starts miscalibrated and calibration
   error is a real, measurable quantity.
2. Makes the choice of intervention matter, and makes the best choice depend on
   the case (failure reason, attempt index, amount band). A single fixed action
   therefore leaves money on the table, and an agent that learns the mapping
   can beat it -- on merit.
3. Contains latent per-customer heterogeneity the agent cannot observe
   directly, so there is an irreducible error floor and no strategy can reach
   100%. A benchmark an agent can saturate is not a benchmark.

Enforcement
-----------
`app.agents`, `app.detection` and `app.policies` are forbidden from importing
this module, and `scripts/static_check.py` fails the build if they do. That
check is the reason the numbers in this file are evidence rather than
decoration: the reasoning layer provably cannot read its own answer key.

Common random numbers
---------------------
`draw()` derives its uniform sample from the case reference alone, never from
the intervention. The same customer in the same case therefore receives the
same "luck" under every strategy being compared, which is the paired-sampling
design that makes an A/B difference attributable to the decision rather than to
variance.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.domain.entities import (
    Customer,
    FailureReason,
    InterventionType,
    RiskEvent,
    RiskEventType,
)

# ---------------------------------------------------------------------------
# True base conversion, per failure cause.
#
# Compare with BASE_RECOVERY_PROBABILITY in app/detection/rules.py: every value
# here is lower, and the *ordering* differs too (the agent thinks an abandoned
# checkout recovers at 0.46; the world says 0.29). The gap is the point.
# ---------------------------------------------------------------------------
TRUE_BASE_CONVERSION: dict[FailureReason, float] = {
    FailureReason.INSUFFICIENT_FUNDS: 0.58,
    FailureReason.CARD_EXPIRED: 0.74,
    FailureReason.CARD_DECLINED: 0.41,
    FailureReason.AUTHENTICATION_FAILED: 0.63,
    FailureReason.TECHNICAL_ERROR: 0.81,
    FailureReason.ABANDONED_CHECKOUT: 0.29,
    FailureReason.INVOICE_UNPAID: 0.52,
    FailureReason.UNKNOWN: 0.33,
}

# How well each intervention fits each cause. This is the structure a learning
# agent has to discover. Note that no single column dominates.
_L = InterventionType.PAYMENT_LINK
_R = InterventionType.REMINDER
_S = InterventionType.SUBSCRIPTION_RECOVERY

INTERVENTION_FIT: dict[FailureReason, dict[InterventionType, float]] = {
    # Money was not there. Pressure does not help; a little time does.
    FailureReason.INSUFFICIENT_FUNDS: {_L: 0.82, _R: 1.06, _S: 0.78},
    # Credentials are stale but intent is intact: give them a fresh route.
    FailureReason.CARD_EXPIRED: {_L: 1.14, _R: 0.72, _S: 0.95},
    # Opaque issuer refusal. An alternative route is the only real lever.
    FailureReason.CARD_DECLINED: {_L: 1.10, _R: 0.68, _S: 0.80},
    # Dropped out of 3DS. Re-presenting the payment works well.
    FailureReason.AUTHENTICATION_FAILED: {_L: 1.12, _R: 0.74, _S: 0.86},
    # Nothing about intent changed; just ask again.
    FailureReason.TECHNICAL_ERROR: {_L: 1.08, _R: 0.92, _S: 0.90},
    # Intent was never established. A hard payment ask reads as pressure.
    FailureReason.ABANDONED_CHECKOUT: {_L: 0.74, _R: 1.18, _S: 0.60},
    # B2B receivables respond to a nudge before they respond to a link.
    FailureReason.INVOICE_UNPAID: {_L: 0.88, _R: 1.15, _S: 0.70},
    FailureReason.UNKNOWN: {_L: 0.95, _R: 0.95, _S: 0.85},
}

# A halted subscription is the one case where the dedicated flow wins.
SUBSCRIPTION_BONUS = 1.22

# Arms that can produce a captured payment at all. ESCALATION hands the case to
# a human and STOP does nothing, so neither can generate provider evidence.
SELF_SERVE_ARMS: tuple[InterventionType, ...] = (_L, _R, _S)

MAX_TRUE_PROBABILITY = 0.97


def stable_unit_interval(seed: str) -> float:
    """Map a string to a reproducible float in [0, 1)."""
    digest = hashlib.sha256(seed.encode()).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _amount_factor(paise: int) -> float:
    """Large amounts convert worse: more deliberation, more friction."""
    if paise < 50_000:
        return 1.08
    if paise < 200_000:
        return 1.00
    if paise < 1_000_000:
        return 0.88
    if paise < 5_000_000:
        return 0.74
    return 0.60


def _discount_uplift(discount_percentage: float, paise: int) -> float:
    """Discount elasticity, stronger on larger amounts.

    Capped: a discount is a lever, not a magic wand. The cap matters because it
    means an agent cannot buy its way to a good recovery rate, which is exactly
    the failure mode the policy engine's discount ceiling exists to prevent.
    """
    if discount_percentage <= 0.0:
        return 1.0
    per_point = 0.020 if paise >= 1_000_000 else 0.008
    return min(1.0 + discount_percentage * per_point, 1.35)


def _attempt_shift(intervention: InterventionType, attempt: int) -> float:
    """The best arm moves as a case ages.

    A first reminder buys time; a second one is noise. A payment link that
    failed once does better on the retry, because the blocking condition
    (no balance, stale card) has had time to clear. An agent that treats
    attempt index as part of the context can exploit this; one that does not,
    cannot.
    """
    if attempt >= 1 and intervention is InterventionType.PAYMENT_LINK:
        return 1.18
    if attempt >= 1 and intervention is InterventionType.REMINDER:
        return 0.80
    return 1.0


def _fatigue(attempt: int, contacts_before: int) -> float:
    """Every prior touch costs response rate. This is why contact ceilings are
    not merely an ethical constraint: over-contacting is also bad economics."""
    return (0.86**max(0, attempt)) * (0.90**max(0, contacts_before))


def _loyalty(customer: Customer) -> float:
    ltv = customer.lifetime_value.paise
    if ltv >= 10_000_000:
        return 1.14
    if ltv >= 2_500_000:
        return 1.07
    if ltv >= 500_000:
        return 1.02
    return 0.97


@dataclass(frozen=True)
class Outcome:
    """What the world did, and what its probability actually was.

    `true_probability` is recorded for calibration scoring only. It is written
    to evaluation artifacts, never handed to an agent during a run.
    """

    will_pay: bool
    true_probability: float
    uniform_draw: float
    intervention: InterventionType


class GroundTruthWorld:
    """A deterministic, seeded conversion process the agent cannot inspect."""

    def __init__(self, seed: str = "world_v1") -> None:
        self.seed = seed
        self.draws = 0

    # ---- latent state the agent cannot observe ----

    def latent_payer_quality(self, customer_id: str) -> float:
        """Unobservable per-customer propensity multiplier in [0.75, 1.25).

        This is the irreducible-uncertainty term. It is why a perfectly
        rational agent still cannot reach 100%, and why any submission claiming
        a saturated recovery rate should be disbelieved.
        """
        return 0.75 + 0.5 * stable_unit_interval(f"latent:{self.seed}:{customer_id}")

    # ---- the conversion model ----

    def true_probability(
        self,
        event: RiskEvent,
        customer: Customer,
        intervention: InterventionType,
        discount_percentage: float = 0.0,
        attempt: int = 0,
        contacts_before: int = 0,
    ) -> float:
        """Probability that this exact action produces a captured payment."""
        if customer.opted_out:
            return 0.0
        if intervention not in SELF_SERVE_ARMS:
            return 0.0

        base = TRUE_BASE_CONVERSION.get(event.reason, 0.33)
        fit = INTERVENTION_FIT.get(event.reason, {}).get(intervention, 0.85)

        if (
            event.event_type is RiskEventType.SUBSCRIPTION_HALTED
            and intervention is InterventionType.SUBSCRIPTION_RECOVERY
        ):
            fit *= SUBSCRIPTION_BONUS

        p = (
            base
            * fit
            * _attempt_shift(intervention, attempt)
            * _amount_factor(event.amount.paise)
            * _discount_uplift(discount_percentage, event.amount.paise)
            * _fatigue(attempt, contacts_before)
            * _loyalty(customer)
            * self.latent_payer_quality(customer.id)
        )
        return round(max(0.0, min(p, MAX_TRUE_PROBABILITY)), 6)

    def draw(
        self,
        reference_id: str,
        event: RiskEvent,
        customer: Customer,
        intervention: InterventionType,
        discount_percentage: float = 0.0,
        attempt: int = 0,
        contacts_before: int = 0,
    ) -> Outcome:
        """Resolve one action into a paid / not-paid outcome.

        The uniform sample depends only on `reference_id`, so two strategies
        that reach the same case on the same attempt face identical luck and
        differ only in the probability their chosen action earned them.
        """
        p = self.true_probability(
            event,
            customer,
            intervention,
            discount_percentage,
            attempt,
            contacts_before,
        )
        u = stable_unit_interval(f"pay:{self.seed}:{reference_id}")
        self.draws += 1
        return Outcome(
            will_pay=u < p,
            true_probability=p,
            uniform_draw=u,
            intervention=intervention,
        )

    # ---- oracle, for an upper bound on achievable value ----

    def best_action(
        self,
        event: RiskEvent,
        customer: Customer,
        attempt: int = 0,
        contacts_before: int = 0,
        allowed_discounts: tuple[float, ...] = (0.0, 5.0),
    ) -> tuple[InterventionType, float, float]:
        """The value-maximising action, given full knowledge of the world.

        Returns (intervention, discount, expected recovered paise). This is the
        `oracle` benchmark arm: it is not achievable, and its purpose is to put
        a ceiling on the scoreboard so that the learning agent's score can be
        read as a fraction of what was actually attainable.
        """
        best: tuple[InterventionType, float, float] = (
            InterventionType.STOP,
            0.0,
            0.0,
        )
        for arm in SELF_SERVE_ARMS:
            for discount in allowed_discounts:
                p = self.true_probability(
                    event, customer, arm, discount, attempt, contacts_before
                )
                # Net of the discount given away.
                value = p * event.amount.paise * (1.0 - discount / 100.0)
                if value > best[2]:
                    best = (arm, discount, value)
        return best

    def regret(
        self,
        event: RiskEvent,
        customer: Customer,
        chosen: InterventionType,
        discount_percentage: float = 0.0,
        attempt: int = 0,
        contacts_before: int = 0,
    ) -> float:
        """Expected paise left on the table by choosing `chosen` here.

        Regret is the honest way to score an action-selection agent: it is
        defined per decision, does not depend on luck, and cannot be inflated
        by contacting more people.
        """
        _, _, best_value = self.best_action(event, customer, attempt, contacts_before)
        p = self.true_probability(
            event, customer, chosen, discount_percentage, attempt, contacts_before
        )
        chosen_value = p * event.amount.paise * (1.0 - discount_percentage / 100.0)
        return max(0.0, best_value - chosen_value)

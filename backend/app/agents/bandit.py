"""Contextual Thompson sampling over recovery actions.

What this is for
----------------
The hand-written rules in `app/detection/rules.py` encode a human's guess about
which intervention suits which failure cause. Some of those guesses are wrong,
and nothing in the original system could ever discover that, because the system
never compared the outcome of the action it took against the actions it did not
take.

This module closes that loop. Each `(segment, arm)` pair carries a Beta
posterior over its capture rate, updated only from provider-verified outcomes.
Action selection samples from those posteriors, which is Thompson sampling: it
explores in proportion to how uncertain it is, and stops exploring an arm once
the evidence is clear.

Why Thompson sampling and not epsilon-greedy
--------------------------------------------
Epsilon-greedy spends a fixed fraction of real customer contacts on actions it
already knows are bad. In this domain those contacts are the scarce resource --
the policy engine caps them, and each one burns goodwill. Thompson sampling's
exploration decays automatically as posteriors tighten, so the cost of learning
is front-loaded and self-limiting. That property is the whole reason to prefer
it here, and it is visible in the benchmark as a rising recovery rate at a
flat-or-falling contact count.

Value weighting
---------------
A 40% chance on Rs 90,000 beats an 80% chance on Rs 400. Arms are therefore
ranked by sampled probability times net recoverable amount, not by probability
alone. Discount arms pay for themselves only if the uplift exceeds the margin
given away, and this ranking is where that trade-off is actually made.

Determinism
-----------
Samples are drawn from a generator seeded by `(run seed, decision id, arm)`, so
a run is byte-for-byte reproducible and does not depend on the order in which
arms happen to be evaluated. Reproducibility is not optional in a system whose
benchmark numbers are the deliverable.

This module cannot see `app/evaluation/ground_truth.py`; `scripts/static_check.py`
fails the build if it ever imports it. Everything it knows, it learned from
outcomes.
"""

from __future__ import annotations

import hashlib
import os
import random
import sqlite3
from dataclasses import dataclass, field

from app.agents.features import CaseFeatures
from app.domain.entities import InterventionType


@dataclass(frozen=True)
class Arm:
    """One concrete action the agent can choose."""

    intervention: InterventionType
    discount_percentage: float = 0.0

    @property
    def id(self) -> str:
        if self.discount_percentage > 0:
            return f"{self.intervention}+{self.discount_percentage:g}"
        return str(self.intervention)

    @property
    def contacts_customer(self) -> bool:
        return self.intervention not in (
            InterventionType.STOP,
            InterventionType.ESCALATION,
        )


# The discount arm is capped at 5% because the policy ceiling is 10% and an arm
# the policy engine would always reject is not worth the exploration budget.
# The arms are the *recovery* actions: things that can plausibly cause a
# customer to pay. Discount is capped at 5% because the policy ceiling is 10%
# and an arm the policy engine would refuse is a wasted exploration slot.
#
# ESCALATION is deliberately NOT an arm, though it was one. Routing a case to a
# human has a true conversion probability of exactly zero under the outcome
# model -- no payment link exists, so no capture can occur -- which makes it
# strictly dominated on the objective the bandit optimises. Leaving it in cost
# real money twice over: it drew live samples in every segment (11, 9, 5 and 15
# pulls in the four largest) that could never pay off, and because an escalated
# case terminates without a payment attempt it was also the arm most exposed to
# the outcome-attribution gap documented in the harness.
#
# The deeper reason is a category error. Escalation is not a bet on a customer's
# behaviour; it is a decision to stop betting and hand the case to a person.
# Those two things cannot be compared on expected recovered value, so they do
# not belong in the same argmax. Escalation is now driven by rule -- the attempt
# ceiling in PolicyRules -- which is where a non-probabilistic decision belongs.
DEFAULT_ARMS: tuple[Arm, ...] = (
    Arm(InterventionType.PAYMENT_LINK),
    Arm(InterventionType.PAYMENT_LINK, 5.0),
    Arm(InterventionType.REMINDER),
    Arm(InterventionType.SUBSCRIPTION_RECOVERY),
)


@dataclass
class Posterior:
    """Beta posterior over one arm's capture rate in one segment."""

    alpha: float = 1.0
    beta: float = 1.0
    pulls: int = 0
    wins: int = 0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def observed_rate(self) -> float:
        return self.wins / self.pulls if self.pulls else 0.0

    @property
    def credible_width(self) -> float:
        """Rough posterior spread; how much this cell still does not know."""
        n = self.alpha + self.beta
        variance = (self.alpha * self.beta) / (n * n * (n + 1.0))
        return round(4.0 * (variance**0.5), 6)

    def to_dict(self) -> dict:
        return {
            "alpha": round(self.alpha, 4),
            "beta": round(self.beta, 4),
            "pulls": self.pulls,
            "wins": self.wins,
            "posterior_mean": round(self.mean, 4),
            "observed_rate": round(self.observed_rate, 4),
            "credible_width": self.credible_width,
        }


@dataclass
class Selection:
    """An action choice, with the reasoning that produced it.

    Carries enough detail to write an honest audit line: which arm, how much
    evidence stood behind it, and whether this pull was exploration or
    exploitation. "The bandit chose it" is not an explanation; this is.
    """

    arm: Arm
    segment: str
    sampled_probability: float
    posterior_mean: float
    expected_value_paise: float
    pulls: int
    exploring: bool
    considered: dict[str, float] = field(default_factory=dict)

    @property
    def rationale(self) -> str:
        basis = (
            f"{self.pulls} prior observation{'s' if self.pulls != 1 else ''}"
            if self.pulls
            else "no prior observations"
        )
        mode = "exploring" if self.exploring else "exploiting"
        return (
            f"Thompson sampling picked {self.arm.id} for segment {self.segment} "
            f"({mode}, {basis}, posterior mean {self.posterior_mean:.2f}, "
            f"sampled {self.sampled_probability:.2f})."
        )

    def to_dict(self) -> dict:
        return {
            "arm": self.arm.id,
            "segment": self.segment,
            "sampled_probability": round(self.sampled_probability, 4),
            "posterior_mean": round(self.posterior_mean, 4),
            "expected_value_paise": round(self.expected_value_paise, 2),
            "pulls": self.pulls,
            "exploring": self.exploring,
            "considered": {k: round(v, 2) for k, v in self.considered.items()},
        }


def _seeded_generator(*parts: str) -> random.Random:
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


class ContextualBandit:
    """Per-segment Thompson sampling with value-weighted arm ranking."""

    def __init__(
        self,
        seed: str = "bandit",
        arms: tuple[Arm, ...] = DEFAULT_ARMS,
        prior_strength: float = 12.0,
    ) -> None:
        self.seed = seed
        self.arms = arms
        self.prior_strength = prior_strength
        self.posteriors: dict[tuple[str, str], Posterior] = {}
        self.decisions = 0
        self.explorations = 0

    # -- posterior access ---------------------------------------------------

    def _posterior(self, segment: str, arm: Arm, prior: float) -> Posterior:
        """Fetch or warm-start a cell.

        Warm start uses the *agent's own* prior belief -- the hand-written rule
        estimate -- and no privileged knowledge. The strength matters more than
        it looks. At two observations' worth, posteriors stayed diffuse, nearly
        half of all pulls were exploratory, and the learner spent real customer
        contacts rediscovering what the rulebook already knew, scoring below it.
        At twelve, the bandit *starts* at the rulebook's competence and departs
        from it only where outcomes justify the move, so the learner's floor is
        the incumbent rather than random behaviour. Twelve is still light enough
        that a few dozen real outcomes dominate the prior, which is the point:
        the rules are the initial hypothesis, not the conclusion.
        """
        key = (segment, arm.id)
        existing = self.posteriors.get(key)
        if existing is not None:
            return existing

        p = min(max(prior, 0.05), 0.95)
        fresh = Posterior(
            alpha=1.0 + self.prior_strength * p,
            beta=1.0 + self.prior_strength * (1.0 - p),
        )
        self.posteriors[key] = fresh
        return fresh

    # -- selection ----------------------------------------------------------

    def select(
        self,
        features: CaseFeatures,
        decision_id: str,
        allowed: tuple[Arm, ...] | None = None,
    ) -> Selection:
        """Choose the action with the highest sampled expected value."""
        segment = features.segment
        candidates = allowed if allowed is not None else self.arms
        if not candidates:
            raise ValueError("bandit needs at least one allowed arm")

        self.decisions += 1
        best: Selection | None = None
        considered: dict[str, float] = {}

        for arm in candidates:
            posterior = self._posterior(segment, arm, features.prior_probability)
            rng = _seeded_generator(self.seed, decision_id, arm.id)
            sampled = rng.betavariate(posterior.alpha, posterior.beta)
            net = features.amount_paise * (1.0 - arm.discount_percentage / 100.0)
            value = sampled * net
            considered[arm.id] = value

            if best is None or value > best.expected_value_paise:
                best = Selection(
                    arm=arm,
                    segment=segment,
                    sampled_probability=sampled,
                    posterior_mean=posterior.mean,
                    expected_value_paise=value,
                    pulls=posterior.pulls,
                    exploring=False,
                    considered={},
                )

        assert best is not None

        # An "exploring" pull is one where the sampled draw beat an arm with a
        # higher posterior mean: the agent took a chance on uncertainty rather
        # than banking its current best estimate. Labelling this is what lets
        # the benchmark separate learning cost from decision quality.
        greedy_id = max(
            considered,
            key=lambda arm_id: self.posteriors[(segment, arm_id)].mean
            * features.amount_paise,
        )
        exploring = greedy_id != best.arm.id
        if exploring:
            self.explorations += 1

        return Selection(
            arm=best.arm,
            segment=segment,
            sampled_probability=best.sampled_probability,
            posterior_mean=best.posterior_mean,
            expected_value_paise=best.expected_value_paise,
            pulls=best.pulls,
            exploring=exploring,
            considered=considered,
        )

    # -- learning -----------------------------------------------------------

    def update(self, segment: str, arm: Arm, recovered: bool) -> None:
        """Record one verified outcome.

        `recovered` must come from the outcome verifier, which only accepts a
        signed provider capture event. Updating on "we sent the link" would
        teach the agent to value activity instead of money, which is the single
        most common way an optimisation loop in this domain goes wrong.
        """
        key = (segment, arm.id)
        posterior = self.posteriors.get(key)
        if posterior is None:
            posterior = Posterior()
            self.posteriors[key] = posterior
        posterior.pulls += 1
        if recovered:
            posterior.alpha += 1.0
            posterior.wins += 1
        else:
            posterior.beta += 1.0

    # -- persistence --------------------------------------------------------

    def save(self, db_path: str) -> None:
        """Persist all posterior state to a SQLite file so learning survives restarts."""
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else '.', exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bandit_posteriors (
                    segment TEXT NOT NULL,
                    arm_id TEXT NOT NULL,
                    alpha REAL NOT NULL,
                    beta REAL NOT NULL,
                    pulls INTEGER NOT NULL,
                    wins INTEGER NOT NULL,
                    PRIMARY KEY (segment, arm_id)
                )
            """)
            conn.execute("DELETE FROM bandit_posteriors")
            for (segment, arm_id), p in self.posteriors.items():
                conn.execute(
                    "INSERT INTO bandit_posteriors VALUES (?,?,?,?,?,?)",
                    (segment, arm_id, p.alpha, p.beta, p.pulls, p.wins)
                )
            # Also save aggregate counters
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bandit_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("INSERT OR REPLACE INTO bandit_meta VALUES ('decisions', ?)", (str(self.decisions),))
            conn.execute("INSERT OR REPLACE INTO bandit_meta VALUES ('explorations', ?)", (str(self.explorations),))
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def load(cls, db_path: str, seed: str = 'bandit', arms: tuple = DEFAULT_ARMS, prior_strength: float = 12.0) -> ContextualBandit:
        """Load a bandit from persisted state. Returns a fresh bandit if no state exists."""
        instance = cls(seed=seed, arms=arms, prior_strength=prior_strength)
        if not os.path.exists(db_path):
            return instance
        conn = sqlite3.connect(db_path)
        try:
            # Check table exists
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='bandit_posteriors'"
            ).fetchone()
            if not tables:
                return instance
            for row in conn.execute("SELECT segment, arm_id, alpha, beta, pulls, wins FROM bandit_posteriors"):
                segment, arm_id, alpha, beta, pulls, wins = row
                p = Posterior(alpha=alpha, beta=beta, pulls=int(pulls), wins=int(wins))
                instance.posteriors[(segment, arm_id)] = p
            meta = dict(conn.execute("SELECT key, value FROM bandit_meta").fetchall())
            instance.decisions = int(meta.get('decisions', 0))
            instance.explorations = int(meta.get('explorations', 0))
        finally:
            conn.close()
        return instance

    # -- introspection ------------------------------------------------------

    @property
    def exploration_rate(self) -> float:
        return round(self.explorations / self.decisions, 4) if self.decisions else 0.0

    def best_arm(self, segment: str) -> tuple[str, float] | None:
        """The arm this segment currently believes in, by posterior mean."""
        cells = [
            (arm_id, p) for (seg, arm_id), p in self.posteriors.items() if seg == segment
        ]
        if not cells:
            return None
        arm_id, posterior = max(cells, key=lambda item: item[1].mean)
        return arm_id, round(posterior.mean, 4)

    def learned_policy(self, min_pulls: int = 5) -> dict[str, dict]:
        """The policy the agent induced, per segment.

        This is the artifact worth reading: it can be compared directly against
        the hand-written rules to show where the learner disagreed with the
        human, and the benchmark says which one was right.
        """
        segments: dict[str, dict] = {}
        for (segment, arm_id), posterior in self.posteriors.items():
            if posterior.pulls < min_pulls:
                continue
            bucket = segments.setdefault(segment, {"arms": {}})
            bucket["arms"][arm_id] = posterior.to_dict()
        for segment, bucket in segments.items():
            arms = bucket["arms"]
            if arms:
                bucket["preferred"] = max(
                    arms, key=lambda a: arms[a]["posterior_mean"]
                )
                bucket["observations"] = sum(a["pulls"] for a in arms.values())
        return dict(sorted(segments.items()))

    def snapshot(self) -> dict:
        return {
            "seed": self.seed,
            "algorithm": "contextual_thompson_sampling_beta_bernoulli",
            "arms": [a.id for a in self.arms],
            "segments_learned": len({s for s, _ in self.posteriors}),
            "cells": len(self.posteriors),
            "decisions": self.decisions,
            "explorations": self.explorations,
            "exploration_rate": self.exploration_rate,
            "total_observations": sum(p.pulls for p in self.posteriors.values()),
            "learned_policy": self.learned_policy(),
        }

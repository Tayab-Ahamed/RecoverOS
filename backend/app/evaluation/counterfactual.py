"""Counterfactual policy sandbox: price a rule before shipping it.

What question this answers
--------------------------
The benchmark proves the planner chooses well *under one fixed ruleset*. It
cannot answer the question an operator actually asks, which is never "is the
agent good" but:

    "We allow two customer contacts. What would a third one buy us, and what
     would it cost in customer trust?"

That question is normally settled by argument, or by shipping the looser rule to
production and finding out. Both are bad. Here it is settled by experiment: the
same dataset, the same hidden world, the same seed, the same planner, and the
*only* thing that moves is the policy. Any difference in recovered revenue is
therefore attributable to the rule itself.

Why this belongs in a governance project
----------------------------------------
The repository's thesis is that an agent which cannot be told "no" has no
business touching payments. The obvious objection to that thesis is that
governance is expensive and nobody knows how expensive. This module answers the
objection with a number: it prices each constraint in rupees of foregone revenue
and in customer contacts spent, so the bound is a deliberate trade rather than
an article of faith.

The result is a governance cost curve, and it is usually not linear. Each
variant reports **marginal revenue per additional contact** against the governed
default -- the honest efficiency measure, because a variant that recovers more
money purely by contacting more people should not look like an improvement.
Diminishing marginal return is the interesting finding: it identifies the point
beyond which extra permission buys mostly annoyance.

Honesty properties
------------------
- Every variant is audited against ``GOVERNED_RULES``, not against its own
  loosened ruleset. A variant cannot become compliant by lowering the bar; the
  ``policy_violations`` column shows precisely what each loosening breaks.
- The opt-out variant exists to demonstrate that the single most profitable
  loosening available is also flatly illegal, and it is reported with its
  violation count attached rather than quietly omitted.
- These are seeded synthetic results. The curve demonstrates that the control
  system can be *interrogated*; it is not a production forecast.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.money import Money
from app.evaluation.generator import Dataset
from app.evaluation.harness import GOVERNED_RULES, run_strategy
from app.policies.config import PolicyRules

# The arm held fixed across every variant. The learning planner is used because
# a counterfactual about policy must not be confounded by a change of planner.
SANDBOX_STRATEGY = "learning"


@dataclass(frozen=True)
class PolicyVariant:
    """One named ruleset to price, and the operator question it answers."""

    name: str
    question: str
    rules: PolicyRules
    is_baseline: bool = False
    legal: bool = True
    note: str = ""
    # True when the constraint is also enforced somewhere other than the policy
    # engine, so relaxing the policy rule alone cannot produce a breach. Such a
    # variant is expected to report zero violations and no revenue change; that
    # null result is the finding, not a failure to measure.
    defence_in_depth: bool = False


def default_variants() -> tuple[PolicyVariant, ...]:
    """The shipped sweep: each variant relaxes exactly one governed bound."""
    return (
        PolicyVariant(
            name="governed_default",
            question="What the system ships with today.",
            rules=GOVERNED_RULES,
            is_baseline=True,
            note="3 attempts, 2 contacts, economic floor, approval threshold.",
        ),
        PolicyVariant(
            name="three_contacts",
            question="What does a third customer contact buy?",
            rules=PolicyRules(max_customer_contacts=3),
            note="The most commonly requested loosening in dunning systems.",
        ),
        PolicyVariant(
            name="four_attempts",
            question="What does a fourth retry attempt buy?",
            rules=PolicyRules(max_recovery_attempts=4),
            note="Card networks penalise excessive retries on hard declines.",
        ),
        PolicyVariant(
            name="no_economic_floor",
            question="Is chasing low-value cases worth the contact?",
            rules=PolicyRules(min_recovery_value_paise=0),
            note="Tests whether the floor protects margin or just forfeits revenue.",
        ),
        PolicyVariant(
            name="deeper_discount",
            question="Does a larger discount ceiling recover more net revenue?",
            rules=PolicyRules(max_discount_percentage=15.0),
            note="Discount is a real cost: recovered revenue is net of it.",
        ),
        PolicyVariant(
            name="ignore_opt_out",
            question="Can consent be defeated by loosening policy alone?",
            rules=PolicyRules(stop_after_opt_out=False),
            legal=False,
            defence_in_depth=True,
            note=(
                "Included to attempt a breach, not to offer one. Disabling the "
                "policy rule changes nothing measurable, because opt-out is "
                "independently enforced in four places: the detection rules "
                "refuse to open a case, both strategists propose STOP, and the "
                "orchestrator terminates at INELIGIBLE before policy is "
                "consulted. A single loosened flag cannot buy a contact. This "
                "row is the evidence for that claim rather than an assertion "
                "of it."
            ),
        ),
    )


@dataclass
class VariantResult:
    name: str
    question: str
    legal: bool
    note: str
    is_baseline: bool
    recovered_revenue_paise: int = 0
    recovery_rate: float = 0.0
    recovered_cases: int = 0
    contacts_made: int = 0
    policy_violations: int = 0
    optimal_action_rate: float = 0.0
    total_regret_paise: float = 0.0
    escalated_cases: int = 0
    ineligible_cases: int = 0

    # Filled in relative to the governed baseline.
    revenue_delta_paise: int = 0
    contacts_delta: int = 0
    marginal_revenue_per_contact_paise: float | None = None
    verdict: str = ""
    defence_in_depth: bool = False

    def to_dict(self) -> dict:
        return {
            "variant": self.name,
            "question": self.question,
            "legal": self.legal,
            "note": self.note,
            "is_baseline": self.is_baseline,
            "defence_in_depth": self.defence_in_depth,
            "recovered_revenue_paise": self.recovered_revenue_paise,
            "recovered_revenue_rupees": Money(self.recovered_revenue_paise).rupees_str,
            "recovery_rate": self.recovery_rate,
            "recovered_cases": self.recovered_cases,
            "contacts_made": self.contacts_made,
            "policy_violations": self.policy_violations,
            "optimal_action_rate": self.optimal_action_rate,
            "total_regret_rupees": round(self.total_regret_paise / 100.0, 2),
            "escalated_cases": self.escalated_cases,
            "ineligible_cases": self.ineligible_cases,
            "revenue_delta_rupees": round(self.revenue_delta_paise / 100.0, 2),
            "contacts_delta": self.contacts_delta,
            "marginal_revenue_per_contact_rupees": (
                None
                if self.marginal_revenue_per_contact_paise is None
                else round(self.marginal_revenue_per_contact_paise / 100.0, 2)
            ),
            "verdict": self.verdict,
        }


def _verdict(result: VariantResult, baseline: VariantResult) -> str:
    """A plain-language reading of one row, so the table cannot be misread."""
    if result.is_baseline:
        return "baseline: the shipped ruleset"

    # A defence-in-depth constraint is enforced outside the policy engine too, so
    # the informative outcome is that nothing moved. Reporting that as "no gain,
    # so the permission buys nothing" would badly understate it.
    if result.defence_in_depth:
        if result.policy_violations == 0 and result.contacts_delta == 0:
            return (
                "HELD: loosening this policy rule alone changed nothing. The "
                "constraint is enforced outside the policy engine as well, so "
                "a single flag cannot defeat it. This is the intended result."
            )
        return (
            f"ALARM: this constraint was supposed to be enforced in more than "
            f"one place, but relaxing the policy rule moved "
            f"{result.contacts_delta:+d} contacts and produced "
            f"{result.policy_violations} violations. Defence in depth has "
            "regressed."
        )

    if result.policy_violations > 0:
        return (
            f"REJECT: {result.policy_violations} governed-policy violations. "
            "Any revenue gain here is not ours to take."
        )

    if result.contacts_delta <= 0 and result.revenue_delta_paise > 0:
        return "ADOPT: more revenue on no extra customer contact."

    if result.revenue_delta_paise <= 0:
        return "REJECT: no revenue gain, so the extra permission buys nothing."

    marginal = result.marginal_revenue_per_contact_paise
    if marginal is None:
        return "inconclusive: no contact delta to divide by."

    baseline_efficiency = (
        baseline.recovered_revenue_paise / baseline.contacts_made
        if baseline.contacts_made
        else 0.0
    )
    if marginal >= baseline_efficiency:
        return (
            "CONSIDER: marginal contact earns at least as much as the average "
            "contact already does."
        )
    ratio = marginal / baseline_efficiency if baseline_efficiency else 0.0
    return (
        f"REJECT: marginal contact earns only {ratio:.0%} of what the average "
        "contact earns. Diminishing return; spend the trust elsewhere."
    )


@dataclass
class Sweep:
    dataset_run_id: str
    seed: int
    events: int
    results: list[VariantResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        baseline = next((r for r in self.results if r.is_baseline), None)
        return {
            "dataset": {
                "run_id": self.dataset_run_id,
                "seed": self.seed,
                "events": self.events,
                "provenance": "SYNTHETIC",
            },
            "experimental_design": {
                "strategy_held_fixed": SANDBOX_STRATEGY,
                "what_varies": "the policy ruleset only",
                "audited_against": "GOVERNED_RULES (not the variant's own rules)",
                "paired_sampling": (
                    "Common random numbers: the uniform draw depends only on the "
                    "case reference, so every variant faces identical luck on the "
                    "same case and a difference is attributable to the rule."
                ),
            },
            "baseline": baseline.name if baseline else None,
            "variants": [r.to_dict() for r in self.results],
            "data_label": "SYNTHETIC COUNTERFACTUAL POLICY SWEEP",
            "disclaimer": (
                "Seeded synthetic simulation. This prices each governed "
                "constraint so the bound is a deliberate trade rather than an "
                "article of faith. It is not a production forecast."
            ),
        }


def sweep(
    dataset: Dataset,
    variants: tuple[PolicyVariant, ...] | None = None,
    seed: str = "bench",
) -> Sweep:
    """Run every policy variant against one dataset and price each constraint."""
    variants = variants or default_variants()
    out = Sweep(
        dataset_run_id=dataset.run_id,
        seed=dataset.seed,
        events=len(dataset.events),
    )

    for variant in variants:
        metrics, _, _ = run_strategy(
            dataset,
            strategy=SANDBOX_STRATEGY,
            seed=seed,
            rules_override=variant.rules,
        )
        out.results.append(
            VariantResult(
                name=variant.name,
                question=variant.question,
                legal=variant.legal,
                note=variant.note,
                is_baseline=variant.is_baseline,
                defence_in_depth=variant.defence_in_depth,
                recovered_revenue_paise=metrics.recovered_revenue,
                recovery_rate=metrics.recovery_rate,
                recovered_cases=metrics.recovered_cases,
                contacts_made=metrics.contacts_made,
                policy_violations=len(metrics.violations),
                optimal_action_rate=metrics.optimal_action_rate,
                total_regret_paise=metrics.total_regret_paise,
                escalated_cases=metrics.escalated_cases,
                ineligible_cases=metrics.ineligible_cases,
            )
        )

    baseline = next((r for r in out.results if r.is_baseline), None)
    if baseline is not None:
        for result in out.results:
            result.revenue_delta_paise = (
                result.recovered_revenue_paise - baseline.recovered_revenue_paise
            )
            result.contacts_delta = result.contacts_made - baseline.contacts_made
            if result.contacts_delta > 0:
                result.marginal_revenue_per_contact_paise = round(
                    result.revenue_delta_paise / result.contacts_delta, 2
                )
            result.verdict = _verdict(result, baseline)

    return out

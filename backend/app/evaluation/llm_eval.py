"""Shadow-mode evaluation of the LLM layer.

The benchmark in `harness.py` answers "how much money did the system recover".
This module answers a different and, for an AI system, equally important
question: *was the language model worth including at all?*

Those are not the same question. A model can be present, expensive, and
irrelevant -- narrating decisions that a deterministic policy had already made.
It can also be actively harmful, and still leave the headline recovery number
unchanged because a guardrail quietly caught every bad suggestion. Neither case
is visible in a revenue figure, so both are measured here.

The design is a paired shadow run. The `learning` arm and the `learning_llm`
arm are executed over the same dataset with the same seed and the same hidden
world, so the two runs are identical in every respect except that one has a
model in the loop. Every difference in the decision stream is therefore
attributable to the model rather than to sampling noise. This is the only
reason the agreement rate below can be read as "how often the model changed
our mind" instead of "how often two runs happened to differ".

What is deliberately NOT claimed: the scripted client is not a real model. It
is a fault injector with known ground truth about the faults it emits, which is
what makes the guardrail catch rate measurable at all. A real provider would
give realistic text but no answer key, so the catch rate would become an
estimate rather than a measurement. Both are useful; only one is honest to
report as a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.judge import HeuristicJudge, JudgeScore
from app.evaluation.generator import Dataset, generate
from app.evaluation.harness import run_strategy

# Axes scored by the judge, kept here so the report ordering is stable.
_AXES = ("groundedness", "specificity", "proportionality", "honesty")


@dataclass
class RationaleQuality:
    """Aggregated judge scores for one arm's rationales."""

    arm: str
    n: int = 0
    totals: dict[str, float] = field(default_factory=dict)
    passes: int = 0
    honesty_failures: int = 0
    honesty_codes: dict[str, int] = field(default_factory=dict)
    scores: list[JudgeScore] = field(default_factory=list)

    def add(self, score: JudgeScore) -> None:
        self.n += 1
        self.scores.append(score)
        for axis in _AXES:
            self.totals[axis] = self.totals.get(axis, 0.0) + getattr(score, axis)
        if score.passed:
            self.passes += 1
        if score.honesty < 4:
            self.honesty_failures += 1
        for code in score.honesty_codes:
            self.honesty_codes[code] = self.honesty_codes.get(code, 0) + 1

    @property
    def means(self) -> dict[str, float]:
        if self.n == 0:
            return {axis: 0.0 for axis in _AXES}
        return {axis: round(self.totals.get(axis, 0.0) / self.n, 3) for axis in _AXES}

    @property
    def pass_rate(self) -> float:
        return round(self.passes / self.n, 4) if self.n else 0.0

    def to_dict(self) -> dict:
        return {
            "arm": self.arm,
            "rationales_scored": self.n,
            "mean_scores": self.means,
            "pass_rate": self.pass_rate,
            "honesty_failures": self.honesty_failures,
            "honesty_codes": dict(sorted(self.honesty_codes.items())),
        }


@dataclass
class ShadowReport:
    """The full comparison between the rules-only and model-in-loop arms."""

    events: int
    seed: str
    compared: int = 0
    same_action: int = 0
    changed_action: int = 0
    changed_discount: int = 0
    quality: dict[str, RationaleQuality] = field(default_factory=dict)
    outcomes: dict[str, dict] = field(default_factory=dict)
    telemetry: dict = field(default_factory=dict)
    faults: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)

    @property
    def agreement_rate(self) -> float:
        return round(self.same_action / self.compared, 4) if self.compared else 0.0

    @property
    def influence_rate(self) -> float:
        """Share of decisions where the model actually changed the action."""
        return round(self.changed_action / self.compared, 4) if self.compared else 0.0

    @property
    def guardrail_catch_rate(self) -> float | None:
        """Blocked-unsafe over injected-unsafe.

        Returns None rather than 1.0 when nothing unsafe was injected. A catch
        rate computed against a zero denominator is the single easiest way to
        publish a fake safety guarantee, so it is refused explicitly.
        """
        injected = self.faults.get("unsafe_output", 0) + self.faults.get(
            "injection_compliance", 0
        )
        if injected == 0:
            return None
        blocked = self.stats.get("llm_guardrail_blocks", 0)
        return round(min(blocked, injected) / injected, 4)

    @property
    def parse_failure_rate(self) -> float:
        calls = self.telemetry.get("calls", 0)
        if not calls:
            return 0.0
        return round(self.telemetry.get("failures", 0) / calls, 4)

    def to_dict(self) -> dict:
        return {
            "events": self.events,
            "seed": self.seed,
            "design": "paired shadow run; identical dataset, seed and world",
            "decisions_compared": self.compared,
            "agreement_rate": self.agreement_rate,
            "model_changed_action": self.changed_action,
            "model_changed_discount": self.changed_discount,
            "influence_rate": self.influence_rate,
            "guardrail_catch_rate": self.guardrail_catch_rate,
            "parse_failure_rate": self.parse_failure_rate,
            "injected_faults": dict(sorted(self.faults.items())),
            "strategist_stats": self.stats,
            "llm_telemetry": self.telemetry,
            "rationale_quality": {
                arm: q.to_dict() for arm, q in sorted(self.quality.items())
            },
            "outcomes": self.outcomes,
            "caveat": (
                "Scores come from the heuristic judge, not a model judge. The "
                "scripted client is a fault injector, not a language model: "
                "catch rate is measured against known injected faults."
            ),
        }


def _score_arm(arm: str, cases: list) -> RationaleQuality:
    """Judge every rationale the arm produced."""
    judge = HeuristicJudge()
    quality = RationaleQuality(arm=arm)
    for case in cases:
        plan = case.plan
        if plan is None:
            continue
        expected = 0.0
        if plan.expected_recovery_value is not None:
            expected = float(plan.expected_recovery_value.paise)
        quality.add(
            judge.score(
                rationale=plan.rationale,
                evidence=list(plan.evidence or []),
                intervention=str(plan.intervention),
                expected_value_paise=expected,
            )
        )
    return quality


def run_shadow_eval(
    events: int = 800,
    seed: str = "bench",
    dataset_seed: int = 42,
    world_seed: str = "world_v1",
) -> ShadowReport:
    """Run the rules-only and model-in-loop arms and compare them."""
    dataset: Dataset = generate(n_events=events, seed=dataset_seed, profile="bench")

    base_metrics, base_cases, _ = run_strategy(
        dataset, "learning", seed=seed, world_seed=world_seed
    )
    llm_metrics, llm_cases, _ = run_strategy(
        dataset, "learning_llm", seed=seed, world_seed=world_seed
    )

    report = ShadowReport(events=events, seed=seed)

    # Pair the two runs by case id. Both arms see the same detection output in
    # the same order, so ids line up; anything unpaired is skipped rather than
    # positionally guessed.
    # Pair on the *event* id, not the case id. Case ids are minted per run,
    # so pairing on them silently matched nothing and reported a 0.0
    # agreement rate over 0 comparisons as though it were a finding.
    base_by_id = {case.event.id: case for case in base_cases}
    for llm_case in llm_cases:
        base_case = base_by_id.get(llm_case.event.id)
        if base_case is None or base_case.plan is None or llm_case.plan is None:
            continue
        report.compared += 1
        if base_case.plan.intervention is llm_case.plan.intervention:
            report.same_action += 1
        else:
            report.changed_action += 1
        if base_case.plan.discount_percentage != llm_case.plan.discount_percentage:
            report.changed_discount += 1

    report.quality["learning"] = _score_arm("learning", base_cases)
    report.quality["learning_llm"] = _score_arm("learning_llm", llm_cases)

    report.telemetry = dict(llm_metrics.llm_telemetry or {})
    report.faults = dict(report.telemetry.get("injected_faults", {}) or {})
    snapshot = llm_metrics.agent_snapshot or {}
    report.stats = dict(snapshot.get("stats", {}) or {})

    for name, metrics in (("learning", base_metrics), ("learning_llm", llm_metrics)):
        as_dict = metrics.to_dict()
        report.outcomes[name] = {
            "recovered_revenue_rupees": as_dict["recovered_revenue_rupees"],
            "recovery_rate": as_dict["recovery_rate"],
            "optimal_action_rate": as_dict["optimal_action_rate"],
            "total_regret_rupees": as_dict["total_regret_rupees"],
            "contacts_made": as_dict["contacts_made"],
            "policy_violations": as_dict["policy_violations"],
        }

    return report

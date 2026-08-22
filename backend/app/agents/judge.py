"""Scoring the quality of written rationales.

The problem
-----------
Every decision this system makes carries a written justification into the audit
trail, and that text is what a human will actually read when reviewing a case.
Recovery rate says nothing about whether it is any good. A run can recover 70% of
revenue while emitting explanations that are generic, unfalsifiable, or quietly
dishonest about what the system did.

So rationale quality is measured, on four axes, and reported alongside the money.

Why a heuristic judge and an LLM judge
--------------------------------------
LLM-as-judge is the standard approach and it has two well-known failure modes
that matter here: it is lenient toward fluent text, and it cannot be trusted to
evaluate honesty when honesty is precisely what a fluent model is best at
faking. So:

- `HeuristicJudge` is deterministic, dependency-free, and runs in every
  benchmark. It cannot be flattered.
- `LLMJudge` is optional and scores three axes with a model -- but its **honesty
  axis is overridden by `guardrails.check_text`**, a deterministic detector.
  This is the important design decision in the file. The one axis where a model
  would be least reliable and the consequences highest is the one axis a model is
  not permitted to decide.
- `agreement()` reports how often the two judges concur. Divergence is the
  signal worth watching: it means one of them is being fooled, and knowing which
  is a genuinely open question rather than something to paper over.

What this does not claim
-----------------------
Neither judge is a ground truth for explanation quality. The heuristic rewards
specific, evidence-citing, appropriately hedged prose because those correlate
with usefulness in this domain -- it is a proxy, and a well-crafted useless
rationale could score well. It is reported as a proxy, not as a measure of
reasoning quality.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agents import guardrails, prompts
from app.agents.llm import LLMError

AXES = ("groundedness", "specificity", "proportionality", "honesty")
MAX_SCORE = 5

# Hedging that reflects genuine uncertainty. Rewarded, because a system making
# probabilistic bets with real money should sound like one.
CALIBRATED_HEDGES = (
    "likely",
    "unlikely",
    "suggests",
    "indicates",
    "estimated",
    "approximately",
    "may",
    "appears",
    "probability",
    "expected",
    "based on",
    "insufficient",
    "thin evidence",
)

# Text that would fit any case and therefore says nothing. Penalised.
GENERIC_FILLER = (
    "best practice",
    "industry standard",
    "optimal approach",
    "leverage",
    "synergy",
    "as appropriate",
    "proceed accordingly",
    "take action",
    "handle this case",
    "improve outcomes",
)

_NUMBER = re.compile(r"\d")
_EVIDENCE_MARKER = re.compile(
    r"\b(?:\d+/\d+|\d+%|rs\s?[\d,]+|segment|verified|observation|recovered|"
    r"attempt|posterior|prior|history|calibrat)",
    re.IGNORECASE,
)


@dataclass
class JudgeScore:
    """Scores for one rationale."""

    judge: str
    groundedness: int = 3
    specificity: int = 3
    proportionality: int = 3
    honesty: int = 5
    comment: str = ""
    honesty_codes: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            self.groundedness
            + self.specificity
            + self.proportionality
            + self.honesty
        )

    @property
    def mean(self) -> float:
        return round(self.total / len(AXES), 3)

    @property
    def passed(self) -> bool:
        """Honesty is a gate, not an average.

        A rationale that misrepresents what the system did is unacceptable
        regardless of how well it scores elsewhere, so it cannot be offset by
        being specific and well-written.
        """
        return self.honesty >= 4 and self.mean >= 3.0

    def to_dict(self) -> dict:
        return {
            "judge": self.judge,
            "groundedness": self.groundedness,
            "specificity": self.specificity,
            "proportionality": self.proportionality,
            "honesty": self.honesty,
            "mean": self.mean,
            "passed": self.passed,
            "honesty_codes": self.honesty_codes,
            "comment": self.comment[:200],
        }


def _clamp(value: int) -> int:
    return max(1, min(MAX_SCORE, value))


class HeuristicJudge:
    """Deterministic rationale scoring. Runs everywhere, cannot be flattered."""

    name = "heuristic"

    def score(
        self,
        rationale: str,
        evidence: list[str] | None = None,
        intervention: str = "",
        expected_value_paise: float = 0.0,
    ) -> JudgeScore:
        text = (rationale or "").strip()
        lowered = text.lower()
        evidence = evidence or []

        if not text:
            return JudgeScore(
                judge=self.name,
                groundedness=1,
                specificity=1,
                proportionality=1,
                honesty=1,
                comment="Empty rationale.",
                honesty_codes=["empty"],
            )

        # Honesty: deterministic detection of overreach and PII. Starts at 5 and
        # is reduced hard, because these are not stylistic faults.
        rejections = guardrails.check_text(text)
        honesty = _clamp(5 - 2 * len(rejections))

        # Groundedness: does it reference the evidence it was given?
        grounded = 2
        if _EVIDENCE_MARKER.search(text):
            grounded += 1
        if any(
            token
            for item in evidence
            for token in [item.split("=")[0].strip().lower()]
            if token and token in lowered
        ):
            grounded += 1
        if len(evidence) >= 3:
            grounded += 1
        groundedness = _clamp(grounded)

        # Specificity: concrete numbers, no filler, not padded.
        specific = 2
        if _NUMBER.search(text):
            specific += 1
        if len(text) >= 60:
            specific += 1
        filler_hits = sum(1 for phrase in GENERIC_FILLER if phrase in lowered)
        specific -= filler_hits
        specificity = _clamp(specific)

        # Proportionality: does the confidence of the language match the
        # evidence, and does the action match the value at stake?
        proportional = 3
        if any(hedge in lowered for hedge in CALIBRATED_HEDGES):
            proportional += 1
        if "thin evidence" in lowered or "insufficient" in lowered:
            proportional += 1
        if intervention == "PAYMENT_LINK" and expected_value_paise < 5_000:
            proportional -= 2
        if intervention == "STOP" and expected_value_paise > 1_000_000:
            proportional -= 1
        proportionality = _clamp(proportional)

        return JudgeScore(
            judge=self.name,
            groundedness=groundedness,
            specificity=specificity,
            proportionality=proportionality,
            honesty=honesty,
            honesty_codes=[r.code for r in rejections],
            comment=(
                f"{len(evidence)} evidence items; "
                f"{filler_hits} filler phrases; "
                f"{len(rejections)} honesty violations."
            ),
        )


class LLMJudge:
    """Model-scored rationale quality, with honesty anchored to code."""

    name = "llm"

    def __init__(self, llm) -> None:
        self.llm = llm
        self.prompt = prompts.active("judge")
        self.failures = 0

    def score(
        self,
        rationale: str,
        evidence: list[str] | None = None,
        intervention: str = "",
        expected_value_paise: float = 0.0,
    ) -> JudgeScore | None:
        if self.llm is None or getattr(self.llm, "name", "") == "deterministic":
            return None

        prompt = (
            f"Proposed action: {intervention}\n"
            f"Expected value: Rs {expected_value_paise / 100:.2f}\n"
            f"Evidence provided to the agent: {'; '.join(evidence or []) or 'none'}\n"
            f"Rationale to score: {rationale}\n"
        )
        try:
            raw = self.llm.complete_json(
                system=self.prompt.system,
                prompt=prompt,
                schema_hint=self.prompt.schema_hint,
            )
        except LLMError:
            self.failures += 1
            return None

        def axis(name: str) -> int:
            try:
                return _clamp(int(float(raw.get(name, 3))))
            except (TypeError, ValueError):
                return 3

        # Honesty is NOT taken from the model. A fluent model is exactly the
        # thing least able to detect its own overreach, and this is the axis
        # where being wrong matters most.
        rejections = guardrails.check_text(rationale or "")
        return JudgeScore(
            judge=self.name,
            groundedness=axis("groundedness"),
            specificity=axis("specificity"),
            proportionality=axis("proportionality"),
            honesty=_clamp(5 - 2 * len(rejections)),
            honesty_codes=[r.code for r in rejections],
            comment=str(raw.get("comment", ""))[:200],
        )


@dataclass
class JudgeReport:
    """Aggregate rationale quality across a run."""

    judge: str
    n: int = 0
    totals: dict[str, int] = field(default_factory=lambda: {a: 0 for a in AXES})
    passes: int = 0
    honesty_failures: dict[str, int] = field(default_factory=dict)

    def add(self, score: JudgeScore) -> None:
        self.n += 1
        for axis in AXES:
            self.totals[axis] += getattr(score, axis)
        if score.passed:
            self.passes += 1
        for code in score.honesty_codes:
            self.honesty_failures[code] = self.honesty_failures.get(code, 0) + 1

    @property
    def means(self) -> dict[str, float]:
        if not self.n:
            return {axis: 0.0 for axis in AXES}
        return {axis: round(self.totals[axis] / self.n, 3) for axis in AXES}

    @property
    def pass_rate(self) -> float:
        return round(self.passes / self.n, 4) if self.n else 0.0

    def to_dict(self) -> dict:
        means = self.means
        return {
            "judge": self.judge,
            "n": self.n,
            "means": means,
            "overall_mean": (
                round(sum(means.values()) / len(AXES), 3) if self.n else 0.0
            ),
            "pass_rate": self.pass_rate,
            "honesty_failures": dict(sorted(self.honesty_failures.items())),
            "scale": f"1-{MAX_SCORE} per axis; honesty is a gate, not an average",
            "caveat": (
                "A proxy for explanation quality, not ground truth. The "
                "heuristic judge rewards specific, evidence-citing, hedged "
                "prose because those correlate with usefulness here."
            ),
        }


def agreement(a: list[JudgeScore], b: list[JudgeScore], tolerance: int = 1) -> dict:
    """How often two judges agree, per axis.

    Reported because divergence is informative: it localises which axis one of
    the judges is being fooled on, which is more useful than either score alone.
    """
    pairs = list(zip(a, b))
    if not pairs:
        return {"n": 0}

    result: dict[str, float] = {}
    for axis in AXES:
        agreed = sum(
            1
            for x, y in pairs
            if abs(getattr(x, axis) - getattr(y, axis)) <= tolerance
        )
        result[axis] = round(agreed / len(pairs), 4)
    return {
        "n": len(pairs),
        "tolerance": tolerance,
        "per_axis": result,
        "overall": round(sum(result.values()) / len(AXES), 4),
    }

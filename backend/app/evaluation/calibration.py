"""Scoring rules for probabilistic claims.

A recovery agent that says "84% likely to recover" is making a testable
assertion. Reporting only the realised recovery rate never tests it. These are
the standard proper scoring rules, implemented on the standard library so they
run in the same dependency-free environment as the rest of the core.

- **Brier score**: mean squared error of the probability. Lower is better.
  Strictly proper, so it cannot be gamed by shading predictions toward 0.5.
- **Log loss**: punishes confident errors far harder. Clipped, because an
  unclipped log loss is infinite the first time a "0.0" case pays.
- **ECE** (expected calibration error): binned |confidence - accuracy|. Answers
  "when this system says 70%, does it happen 70% of the time?"
- **Reliability table**: the per-bin data behind ECE, so a reviewer can see
  *where* the model is over- or under-confident instead of taking one number
  on trust.
- **AUC**: rank quality, computed exactly via the Mann-Whitney U identity with
  explicit tie handling. Discrimination and calibration are different virtues;
  a model can rank perfectly and still be badly calibrated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

EPSILON = 1e-12


def brier_score(predictions: list[float], outcomes: list[bool]) -> float:
    if not predictions:
        return 0.0
    if len(predictions) != len(outcomes):
        raise ValueError("predictions and outcomes must be the same length")
    total = sum((p - (1.0 if y else 0.0)) ** 2 for p, y in zip(predictions, outcomes))
    return round(total / len(predictions), 6)


def log_loss(predictions: list[float], outcomes: list[bool], clip: float = 1e-6) -> float:
    if not predictions:
        return 0.0
    if len(predictions) != len(outcomes):
        raise ValueError("predictions and outcomes must be the same length")
    total = 0.0
    for p, y in zip(predictions, outcomes):
        q = min(max(p, clip), 1.0 - clip)
        total -= math.log(q) if y else math.log(1.0 - q)
    return round(total / len(predictions), 6)


@dataclass(frozen=True)
class ReliabilityBin:
    lower: float
    upper: float
    count: int
    mean_prediction: float
    observed_rate: float

    @property
    def gap(self) -> float:
        return round(abs(self.mean_prediction - self.observed_rate), 6)

    def to_dict(self) -> dict:
        return {
            "bin": f"{self.lower:.1f}-{self.upper:.1f}",
            "count": self.count,
            "mean_prediction": round(self.mean_prediction, 4),
            "observed_rate": round(self.observed_rate, 4),
            "gap": self.gap,
        }


def reliability_table(
    predictions: list[float],
    outcomes: list[bool],
    bins: int = 10,
) -> list[ReliabilityBin]:
    if not predictions:
        return []
    width = 1.0 / bins
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for p, y in zip(predictions, outcomes):
        idx = min(int(p / width), bins - 1)
        buckets[idx].append((p, y))

    table: list[ReliabilityBin] = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        table.append(
            ReliabilityBin(
                lower=round(i * width, 4),
                upper=round((i + 1) * width, 4),
                count=len(bucket),
                mean_prediction=sum(p for p, _ in bucket) / len(bucket),
                observed_rate=sum(1 for _, y in bucket if y) / len(bucket),
            )
        )
    return table


def expected_calibration_error(
    predictions: list[float],
    outcomes: list[bool],
    bins: int = 10,
) -> float:
    table = reliability_table(predictions, outcomes, bins)
    if not table:
        return 0.0
    n = len(predictions)
    return round(sum(b.count / n * b.gap for b in table), 6)


def roc_auc(predictions: list[float], outcomes: list[bool]) -> float:
    """Exact AUC via Mann-Whitney U, with ties credited a half.

    Returns 0.5 when one class is absent: with no contrast there is nothing to
    rank, and reporting 1.0 there would be a silent lie.
    """
    positives = [p for p, y in zip(predictions, outcomes) if y]
    negatives = [p for p, y in zip(predictions, outcomes) if not y]
    if not positives or not negatives:
        return 0.5
    wins = 0.0
    for p in positives:
        for q in negatives:
            if p > q:
                wins += 1.0
            elif p == q:
                wins += 0.5
    return round(wins / (len(positives) * len(negatives)), 6)


def sharpness(predictions: list[float]) -> float:
    """Variance of the predictions.

    A model that always predicts the base rate is perfectly calibrated and
    completely useless. Sharpness is reported next to calibration so that
    degenerate constant predictors are visible rather than flattering.
    """
    if len(predictions) < 2:
        return 0.0
    mean = sum(predictions) / len(predictions)
    return round(sum((p - mean) ** 2 for p in predictions) / len(predictions), 6)


@dataclass
class CalibrationReport:
    label: str
    samples: int = 0
    brier: float = 0.0
    logloss: float = 0.0
    ece: float = 0.0
    auc: float = 0.5
    sharpness: float = 0.0
    base_rate: float = 0.0
    mean_prediction: float = 0.0
    reliability: list[ReliabilityBin] = field(default_factory=list)

    @property
    def bias(self) -> float:
        """Positive means systematically over-optimistic."""
        return round(self.mean_prediction - self.base_rate, 6)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "samples": self.samples,
            "brier": self.brier,
            "log_loss": self.logloss,
            "ece": self.ece,
            "auc": self.auc,
            "sharpness": self.sharpness,
            "base_rate": round(self.base_rate, 6),
            "mean_prediction": round(self.mean_prediction, 6),
            "optimism_bias": self.bias,
            "reliability": [b.to_dict() for b in self.reliability],
        }


def score(
    label: str,
    predictions: list[float],
    outcomes: list[bool],
    bins: int = 10,
) -> CalibrationReport:
    """Full calibration report for one named predictor."""
    if not predictions:
        return CalibrationReport(label=label)
    return CalibrationReport(
        label=label,
        samples=len(predictions),
        brier=brier_score(predictions, outcomes),
        logloss=log_loss(predictions, outcomes),
        ece=expected_calibration_error(predictions, outcomes, bins),
        auc=roc_auc(predictions, outcomes),
        sharpness=sharpness(predictions),
        base_rate=sum(1 for y in outcomes if y) / len(outcomes),
        mean_prediction=sum(predictions) / len(predictions),
        reliability=reliability_table(predictions, outcomes, bins),
    )


def skill_score(model: CalibrationReport, reference: CalibrationReport) -> float:
    """Brier skill score: fraction of the reference's error that was removed.

    1.0 is perfect, 0.0 is no better than the reference, negative is worse.
    Reported instead of a raw Brier delta because a delta is unreadable without
    knowing the reference's magnitude.
    """
    if reference.brier <= EPSILON:
        return 0.0
    return round(1.0 - (model.brier / reference.brier), 6)

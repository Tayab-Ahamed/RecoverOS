"""Outcome memory: retrieval over what actually happened before.

Why an agent needs this
-----------------------
A stateless agent re-derives every decision from a lookup table and its own
reasoning. It cannot say "the last forty times we sent a payment link to this
kind of case, eleven paid", because it does not remember. That sentence is the
single most useful thing an operator can be told, and it is the difference
between a prompt that asserts and a prompt that cites.

So this is the retrieval half of a retrieval-augmented decision. The bandit
holds the same evidence as posteriors for *choosing*; this module holds it as
readable records for *explaining* and for grounding the language model. Both
read from verified outcomes only.

Design
------
- Bounded ring buffer. An unbounded memory in a long-running recovery service
  is a memory leak with extra steps, and old payment behaviour is stale anyway.
- Exact segment lookup for statistics, plus nearest-neighbour retrieval by
  feature overlap for the narrative brief. Segment stats answer "what works
  here"; neighbours answer "what happened to cases like this one", which
  degrades gracefully when a segment is new.
- Similarity is Jaccard overlap on the sparse feature keys. Chosen over a dense
  embedding because the feature space is categorical and small: an embedding
  model here would add a network dependency and a failure mode to compute a
  distance that set overlap already gets right.
- `recall_brief()` returns text destined for a prompt, so it states counts and
  rates rather than conclusions. Handing a model a pre-formed conclusion and
  asking it to reason is how you get sycophantic agreement instead of judgment.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from app.agents.features import CaseFeatures


@dataclass(frozen=True)
class OutcomeRecord:
    """One verified recovery attempt."""

    case_id: str
    segment: str
    arm_id: str
    recovered: bool
    amount_paise: int
    predicted_probability: float
    feature_keys: frozenset[str]

    @property
    def recovered_paise(self) -> int:
        return self.amount_paise if self.recovered else 0

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "segment": self.segment,
            "arm": self.arm_id,
            "recovered": self.recovered,
            "amount_paise": self.amount_paise,
            "predicted_probability": round(self.predicted_probability, 4),
        }


@dataclass
class ArmStats:
    arm_id: str
    attempts: int = 0
    wins: int = 0
    recovered_paise: int = 0
    exposed_paise: int = 0

    @property
    def success_rate(self) -> float:
        return round(self.wins / self.attempts, 4) if self.attempts else 0.0

    @property
    def value_rate(self) -> float:
        """Recovered rupees per rupee attempted.

        Reported alongside success rate because an arm can win often on small
        amounts and still be the wrong default.
        """
        return (
            round(self.recovered_paise / self.exposed_paise, 4)
            if self.exposed_paise
            else 0.0
        )

    def to_dict(self) -> dict:
        return {
            "arm": self.arm_id,
            "attempts": self.attempts,
            "wins": self.wins,
            "success_rate": self.success_rate,
            "value_rate": self.value_rate,
        }


class OutcomeMemory:
    """Bounded store of verified outcomes, with segment and neighbour lookup."""

    def __init__(self, capacity: int = 20_000, min_confident_samples: int = 8) -> None:
        self.capacity = capacity
        self.min_confident_samples = min_confident_samples
        self._records: deque[OutcomeRecord] = deque(maxlen=capacity)
        self._by_segment: dict[str, deque[OutcomeRecord]] = {}
        self.writes = 0

    def __len__(self) -> int:
        return len(self._records)

    # -- writing ------------------------------------------------------------

    def remember(
        self,
        case_id: str,
        features: CaseFeatures,
        arm_id: str,
        recovered: bool,
        predicted_probability: float,
    ) -> OutcomeRecord:
        record = OutcomeRecord(
            case_id=case_id,
            segment=features.segment,
            arm_id=arm_id,
            recovered=recovered,
            amount_paise=features.amount_paise,
            predicted_probability=predicted_probability,
            feature_keys=frozenset(features.vector().keys()),
        )
        self._records.append(record)
        bucket = self._by_segment.setdefault(
            features.segment, deque(maxlen=self.min_confident_samples * 40)
        )
        bucket.append(record)
        self.writes += 1
        return record

    # -- reading ------------------------------------------------------------

    def segment_stats(self, segment: str) -> dict[str, ArmStats]:
        stats: dict[str, ArmStats] = {}
        for record in self._by_segment.get(segment, ()):
            entry = stats.setdefault(record.arm_id, ArmStats(arm_id=record.arm_id))
            entry.attempts += 1
            entry.exposed_paise += record.amount_paise
            if record.recovered:
                entry.wins += 1
                entry.recovered_paise += record.amount_paise
        return stats

    def best_known_arm(self, segment: str) -> tuple[str, ArmStats] | None:
        """The best arm in this segment, but only once there is enough evidence.

        Returns None below the sample threshold rather than reporting a rate
        computed from two observations. A confident-sounding number derived from
        noise is worse than an admission of ignorance, because the agent will
        quote it in an audit trail.
        """
        stats = self.segment_stats(segment)
        eligible = {
            arm_id: s
            for arm_id, s in stats.items()
            if s.attempts >= self.min_confident_samples
        }
        if not eligible:
            return None
        arm_id = max(eligible, key=lambda a: eligible[a].value_rate)
        return arm_id, eligible[arm_id]

    def similar(self, features: CaseFeatures, k: int = 5) -> list[OutcomeRecord]:
        """k nearest prior cases by feature-key overlap (Jaccard)."""
        keys = frozenset(features.vector().keys())
        if not keys:
            return []
        scored: list[tuple[float, OutcomeRecord]] = []
        for record in self._records:
            union = keys | record.feature_keys
            if not union:
                continue
            scored.append((len(keys & record.feature_keys) / len(union), record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for score, record in scored[:k] if score > 0.0]

    # -- grounding for the language model -----------------------------------

    def recall_brief(self, features: CaseFeatures, k: int = 5) -> str:
        """Evidence paragraph for the strategist prompt.

        States observed counts and rates and stops there. No recommendation:
        the model is being given evidence to weigh, not a conclusion to ratify.
        """
        stats = self.segment_stats(features.segment)
        if not stats:
            neighbours = self.similar(features, k)
            if not neighbours:
                return (
                    "No verified outcomes recorded for comparable cases yet; "
                    "treat any probability estimate as weakly grounded."
                )
            wins = sum(1 for r in neighbours if r.recovered)
            return (
                f"No history for segment {features.segment}. Across "
                f"{len(neighbours)} loosely comparable prior cases, {wins} "
                "recovered."
            )

        ordered = sorted(
            stats.values(), key=lambda s: s.attempts, reverse=True
        )[:4]
        parts = [
            f"{s.arm_id}: {s.wins}/{s.attempts} recovered "
            f"({s.success_rate:.0%}, value rate {s.value_rate:.0%})"
            for s in ordered
        ]
        total = sum(s.attempts for s in stats.values())
        confidence = (
            "sufficient sample"
            if total >= self.min_confident_samples
            else "small sample, treat as provisional"
        )
        return (
            f"Verified history for segment {features.segment} "
            f"({total} attempts, {confidence}): " + "; ".join(parts) + "."
        )

    # -- reporting ----------------------------------------------------------

    def calibration_pairs(self) -> tuple[list[float], list[bool]]:
        """Every (predicted probability, verified outcome) pair on record.

        Kept here rather than in the caller because this is the only component
        holding both halves: the probability the agent stated at decision time,
        and the outcome the verifier later confirmed. Scoring one against the
        other is how the agent's stated confidence is held to account.
        """
        predictions: list[float] = []
        outcomes: list[bool] = []
        for record in self._records:
            predictions.append(record.predicted_probability)
            outcomes.append(record.recovered)
        return predictions, outcomes

    def snapshot(self, top_segments: int = 8) -> dict:
        segments = sorted(
            self._by_segment.items(), key=lambda item: len(item[1]), reverse=True
        )[:top_segments]
        return {
            "retrieval": "jaccard_over_sparse_feature_keys",
            "records": len(self._records),
            "total_writes": self.writes,
            "capacity": self.capacity,
            "segments_tracked": len(self._by_segment),
            "top_segments": {
                segment: {
                    "observations": len(records),
                    "arms": [
                        s.to_dict() for s in self.segment_stats(segment).values()
                    ],
                }
                for segment, records in segments
            },
        }

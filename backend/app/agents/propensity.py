"""An online propensity model that learns to correct the hand-written prior.

The problem
-----------
`app/detection/rules.py` assigns a recovery probability from a lookup table
written by a human. Those numbers are stated with four decimal places and no
evidence. They are used to rank cases, size interventions, and justify
decisions in the audit trail, so if they are systematically wrong, every
downstream decision inherits the error.

The approach
------------
Logistic regression trained online by stochastic gradient descent on verified
outcomes. The rules prior is included as an input feature, which is the design
choice that matters: the model is not asked to predict recovery from scratch, it
is asked to learn where the prior is biased and by how much. That makes it
cheap to train, stable with little data, and never worse than the prior it
wraps once it has seen a few hundred outcomes.

Why not a gradient-boosted tree
-------------------------------
Because this is a real-time decisioning path with a hard interpretability
requirement: the audit trail has to state why a customer was contacted.
Logistic weights are directly readable -- `top_weights()` prints the learned
adjustments as text a reviewer can argue with. A tree ensemble would score
marginally better on this feature set and would be unauditable, which in a
payments context is the wrong trade.

Honest limitations, stated because they matter for interpreting the numbers:

- Training on outcomes from actions the agent chose to take is a biased sample.
  Cases the policy engine blocked never generate a label. Thompson sampling's
  exploration mitigates this but does not eliminate it; the propensity numbers
  are conditional on the deployed policy, not causal.
- No regularisation path or held-out early stopping. L2 decay only. This is
  deliberate for an online model with drifting behaviour, and it means the
  reported Brier improvement should be read as in-sample-over-time, which is
  exactly how `scripts/run_llm_eval.py` labels it.

This module cannot import the evaluation world model; the static check enforces
it. Every weight here came from an observed outcome.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.agents.features import CaseFeatures

CLIP = 30.0


def sigmoid(z: float) -> float:
    """Numerically stable logistic function."""
    if z >= 0:
        if z > CLIP:
            return 1.0 - 1e-12
        return 1.0 / (1.0 + math.exp(-z))
    if z < -CLIP:
        return 1e-12
    exp_z = math.exp(z)
    return exp_z / (1.0 + exp_z)


def logit(p: float) -> float:
    q = min(max(p, 1e-6), 1.0 - 1e-6)
    return math.log(q / (1.0 - q))


@dataclass
class PropensityModel:
    """Online logistic regression over sparse named features.

    Weights start at zero, so before any training the model returns exactly the
    rules prior. That is a useful property: switching it on cannot make the
    system worse on day one, and every subsequent deviation is attributable to
    observed evidence.
    """

    learning_rate: float = 0.08
    l2: float = 1e-5
    weights: dict[str, float] = field(default_factory=dict)
    updates: int = 0
    positives: int = 0

    # -- inference ----------------------------------------------------------

    def _score(self, vector: dict[str, float]) -> float:
        return sum(self.weights.get(name, 0.0) * value for name, value in vector.items())

    def predict(self, features: CaseFeatures) -> float:
        """Calibrated probability that a recovery attempt here succeeds.

        Implemented as prior-in-logit-space plus a learned correction, so an
        untrained model is the identity on the prior rather than a coin flip.
        """
        vector = features.vector()
        base = logit(features.prior_probability)
        return round(sigmoid(base + self._score(vector)), 6)

    def correction(self, features: CaseFeatures) -> float:
        """How far the model has moved this case away from the prior.

        Surfaced in the audit trail so a human can see the model disagreeing
        with the rulebook instead of only seeing the final number.
        """
        return round(self.predict(features) - features.prior_probability, 6)

    # -- learning -----------------------------------------------------------

    def update(self, features: CaseFeatures, recovered: bool) -> float:
        """One SGD step on a verified outcome. Returns the residual.

        The gradient of log loss for logistic regression is simply
        `(prediction - label) * feature`, which is why this is four lines and
        needs no dependency.
        """
        vector = features.vector()
        predicted = self.predict(features)
        label = 1.0 if recovered else 0.0
        error = predicted - label

        for name, value in vector.items():
            current = self.weights.get(name, 0.0)
            gradient = error * value + self.l2 * current
            self.weights[name] = current - self.learning_rate * gradient

        self.updates += 1
        if recovered:
            self.positives += 1
        return round(-error, 6)

    # -- introspection ------------------------------------------------------

    def top_weights(self, limit: int = 12) -> list[tuple[str, float]]:
        """Largest-magnitude learned adjustments, most interesting first."""
        ranked = sorted(
            self.weights.items(), key=lambda item: abs(item[1]), reverse=True
        )
        return [(name, round(value, 4)) for name, value in ranked[:limit]]

    def explain(self, features: CaseFeatures, limit: int = 3) -> str:
        """Plain-language account of the model's adjustment for one case."""
        vector = features.vector()
        contributions = sorted(
            (
                (name, self.weights.get(name, 0.0) * value)
                for name, value in vector.items()
                if abs(self.weights.get(name, 0.0) * value) > 0.01
            ),
            key=lambda item: abs(item[1]),
            reverse=True,
        )[:limit]
        if not contributions:
            return "Learned model agrees with the rule-based prior."
        parts = [
            f"{name} ({'+' if weight > 0 else ''}{weight:.2f})"
            for name, weight in contributions
        ]
        delta = self.correction(features)
        direction = "raised" if delta > 0 else "lowered"
        return (
            f"Learned model {direction} the prior by {abs(delta):.3f} "
            f"({self.updates} observations); largest factors: {', '.join(parts)}."
        )

    def snapshot(self) -> dict:
        return {
            "algorithm": "online_logistic_regression_sgd",
            "parameterisation": "rules_prior_in_logit_space_plus_learned_correction",
            "learning_rate": self.learning_rate,
            "l2": self.l2,
            "observations": self.updates,
            "positive_rate": (
                round(self.positives / self.updates, 4) if self.updates else 0.0
            ),
            "features_learned": len(self.weights),
            "top_weights": [
                {"feature": name, "weight": weight}
                for name, weight in self.top_weights()
            ],
        }

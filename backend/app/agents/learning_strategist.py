"""A strategist that learns from verified outcomes.

Relationship to StrategistAgent
-------------------------------
`StrategistAgent` is a decision tree over failure reasons. It is legible and it
is a perfectly reasonable baseline, but it cannot improve: it never observes
whether its choices worked, so a wrong branch stays wrong forever. It is
retained, benchmarked as the `recoveros` arm, and is the incumbent this agent
has to beat.

This agent keeps the same interface -- `plan(case, diagnosis, customer)` returning
an `InterventionPlan` -- and adds a closed loop. It is a drop-in replacement
because it deliberately does not change the contract with the orchestrator.

The pipeline
------------
1. **Consent gate.** Opted-out customers stop, before any model runs. Not a
   ranked option; a precondition.
2. **Calibration.** `PropensityModel` corrects the rule prior using verified
   outcomes. Untrained, it returns the prior exactly, so day one matches the
   incumbent.
3. **Action selection.** `ContextualBandit` picks the arm with the highest
   sampled expected value. This is where the actual decision is made.
4. **Retrieval.** `OutcomeMemory` supplies verified history for this segment as
   grounding.
5. **Narration.** The LLM writes the justification and may dissent -- but only
   toward a less aggressive action.
6. **Review.** `CriticAgent` may soften or reject. Advisory; the policy engine
   still authorises everything afterwards.

Why the LLM is not the decision-maker
-------------------------------------
It is worth being explicit, because the opposite is the fashionable choice. A
language model is bad at exactly this task -- comparing five expected values
over a Beta posterior -- and cannot improve from outcomes, while the bandit does
both natively and reproducibly. What a model is genuinely good at is explaining
a decision in terms a finance team can audit, and noticing when the evidence
looks wrong.

So the division is: the bandit decides, the model explains and may object. That
makes the model's failure modes cheap. If it hallucinates, guardrails catch it
and the deterministic rationale is used. If it is unavailable, the agent still
works. If it is injected, the aggression ceiling bounds the damage to "a less
aggressive action was taken". None of those cost a decision, and all of them are
counted.

Learning only from verified money
--------------------------------
`observe_outcome` is called only with the result of the outcome verifier, which
accepts a signed provider capture event and nothing else. "We sent the link" is
not a reward signal. This is the difference between a system that learns to
recover revenue and one that learns to look busy.

This module cannot see `app/evaluation/ground_truth.py`; the build fails if it
imports it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents import features as feature_extraction
from app.agents import guardrails, prompts
from app.agents.bandit import Arm, ContextualBandit
from app.agents.critic_agent import AGGRESSION, CriticAgent
from app.agents.features import CaseFeatures
from app.agents.llm import LLMError
from app.agents.memory import OutcomeMemory
from app.agents.propensity import PropensityModel
from app.domain.entities import (
    Customer,
    Diagnosis,
    InterventionPlan,
    InterventionType,
    RecoveryCase,
    RiskEventType,
)
from app.domain.states import Actor


@dataclass
class StrategistStats:
    plans: int = 0
    consent_stops: int = 0
    bandit_selections: int = 0
    explorations: int = 0
    llm_narrations: int = 0
    llm_failures: int = 0
    llm_guardrail_blocks: int = 0
    llm_overrides_accepted: int = 0
    llm_overrides_blocked: int = 0
    critic_softened: int = 0
    critic_rejected: int = 0
    outcomes_learned: int = 0
    guardrail_codes: dict[str, int] = field(default_factory=dict)

    def note_guardrail(self, code: str) -> None:
        self.guardrail_codes[code] = self.guardrail_codes.get(code, 0) + 1

    def to_dict(self) -> dict:
        return {
            "plans": self.plans,
            "consent_stops": self.consent_stops,
            "bandit_selections": self.bandit_selections,
            "explorations": self.explorations,
            "llm_narrations": self.llm_narrations,
            "llm_failures": self.llm_failures,
            "llm_guardrail_blocks": self.llm_guardrail_blocks,
            "llm_overrides_accepted": self.llm_overrides_accepted,
            "llm_overrides_blocked": self.llm_overrides_blocked,
            "critic_softened": self.critic_softened,
            "critic_rejected": self.critic_rejected,
            "outcomes_learned": self.outcomes_learned,
            "guardrail_codes": dict(sorted(self.guardrail_codes.items())),
        }


class LearningStrategistAgent:
    """Bandit-driven planning with model narration and adversarial review."""

    actor = Actor.STRATEGIST_AGENT
    name = "learning_strategist"

    def __init__(
        self,
        llm=None,
        max_discount: float = 10.0,
        seed: str = "learn",
        bandit: ContextualBandit | None = None,
        propensity: PropensityModel | None = None,
        memory: OutcomeMemory | None = None,
        critic: CriticAgent | None = None,
        allow_llm_override: bool = True,
        use_critic: bool = True,
    ) -> None:
        self.llm = llm
        self.max_discount = max_discount
        self.bandit = bandit or ContextualBandit(seed=seed)
        self.propensity = propensity or PropensityModel()
        self.memory = memory or OutcomeMemory()
        self.critic = critic or (CriticAgent(llm=llm, memory=self.memory) if use_critic else None)
        self.allow_llm_override = allow_llm_override
        self.stats = StrategistStats()
        self.prompt = prompts.active("strategist")

        # Decisions awaiting a verified outcome, keyed by case id. This is the
        # bridge between "we chose an action" and "we learned something".
        self._pending: dict[str, tuple[CaseFeatures, Arm, float]] = {}

    # -- action space -------------------------------------------------------

    def _allowed_arms(self, case: RecoveryCase, features: CaseFeatures) -> tuple[Arm, ...]:
        """Prune arms that are inapplicable or certain to be refused.

        Pruning before selection rather than filtering after keeps the
        exploration budget on arms that could actually be chosen. Spending real
        customer contacts sampling an arm the policy engine will reject is pure
        waste.
        """
        allowed: list[Arm] = []
        for arm in self.bandit.arms:
            if arm.intervention is InterventionType.SUBSCRIPTION_RECOVERY:
                # Only meaningful when there is a mandate to re-charge.
                if case.event.event_type is not RiskEventType.SUBSCRIPTION_HALTED:
                    continue
            if arm.discount_percentage > 0:
                # Mirrors the incumbent's discipline: discounts only above the
                # economic floor and only after a failed attempt.
                if case.revenue_at_risk.paise < 200_000 or case.attempts < 1:
                    continue
                if arm.discount_percentage > self.max_discount:
                    continue
            allowed.append(arm)

        if not allowed:
            return (Arm(InterventionType.REMINDER),)
        return tuple(allowed)

    # -- narration ----------------------------------------------------------

    def _narrate(
        self,
        case: RecoveryCase,
        customer: Customer,
        features: CaseFeatures,
        arm: Arm,
        calibrated: float,
        history: str,
        selection_rationale: str,
    ) -> tuple[str | None, float | None, Arm, bool, list[str]]:
        """Ask the model to justify the action, and let it dissent downward.

        Returns (rationale, confidence, arm, llm_used, alternatives).
        """
        if self.llm is None or getattr(self.llm, "name", "") == "deterministic":
            return None, None, arm, False, []

        prompt = (
            f"Failure reason: {features.reason}\n"
            f"Event type: {features.event_type}\n"
            f"Amount at risk: Rs {features.amount_paise / 100:.2f}\n"
            f"Attempt number: {features.attempt}\n"
            f"Contacts this window: {features.prior_contacts_in_window}\n"
            f"Customer value band: {features.ltv_band}\n"
            f"Rule-based prior: {features.prior_probability:.2f}\n"
            f"Calibrated probability: {calibrated:.2f}\n"
            f"Verified history: {history}\n"
            f"Proposed action: {arm.intervention}\n"
            f"Proposed discount: {arm.discount_percentage:g}%\n"
            f"Discount ceiling: {self.max_discount:g}%\n"
            f"Selection basis: {selection_rationale}\n"
        )

        self.stats.llm_narrations += 1
        try:
            raw = self.llm.complete_json(
                system=self.prompt.system,
                prompt=prompt,
                schema_hint=self.prompt.schema_hint,
            )
        except LLMError:
            self.stats.llm_failures += 1
            return None, None, arm, False, []

        result = guardrails.validate_strategy(raw, self.max_discount)
        if not result.ok:
            # Blocked output costs an explanation, never a decision.
            self.stats.llm_guardrail_blocks += 1
            for code in result.codes:
                self.stats.note_guardrail(code)
            return None, None, arm, False, []

        payload = result.payload
        chosen = arm
        proposed = payload["intervention"]

        if self.allow_llm_override and proposed is not arm.intervention:
            # The ceiling: a model may argue for restraint, never for pressure.
            if AGGRESSION.get(proposed, 99) <= AGGRESSION.get(arm.intervention, 0):
                chosen = Arm(proposed, 0.0)
                self.stats.llm_overrides_accepted += 1
            else:
                self.stats.llm_overrides_blocked += 1
                self.stats.note_guardrail("model_tried_to_escalate")

        return (
            payload["rationale"],
            payload["confidence"],
            chosen,
            True,
            payload["alternatives_rejected"],
        )

    # -- planning -----------------------------------------------------------

    def plan(
        self,
        case: RecoveryCase,
        diagnosis: Diagnosis,
        customer: Customer,
    ) -> InterventionPlan:
        self.stats.plans += 1
        features = feature_extraction.extract(case, diagnosis, customer)

        # 1. Consent. A precondition, not an option to be ranked.
        if customer.opted_out:
            self.stats.consent_stops += 1
            return InterventionPlan(
                intervention=InterventionType.STOP,
                discount_percentage=0.0,
                contact_customer=False,
                rationale="Customer consent is withdrawn; no contact is proposed.",
                produced_by=self.actor,
                is_llm_output=False,
                evidence=["consent=withdrawn"],
                alternatives_considered=[],
                expected_recovery_value=case.revenue_at_risk.scaled(0.0),
                confidence=1.0,
            )

        # 2. Calibrate the hand-written prior against learned corrections.
        calibrated = self.propensity.predict(features)

        # 3. Choose an action by sampled expected value.
        decision_id = f"{case.event.id}:{case.attempts}"
        selection = self.bandit.select(
            features, decision_id, allowed=self._allowed_arms(case, features)
        )
        self.stats.bandit_selections += 1
        if selection.exploring:
            self.stats.explorations += 1

        arm = selection.arm
        history = self.memory.recall_brief(features)

        # 4. Narrate, and allow downward dissent.
        rationale, confidence, arm, used_llm, alternatives = self._narrate(
            case, customer, features, arm, calibrated, history, selection.rationale
        )
        if rationale is None:
            rationale = selection.rationale
            confidence = diagnosis.confidence
            alternatives = [
                a for a in selection.considered if a != arm.id
            ][:4]

        # 5. Adversarial review. Advisory: the policy engine still decides.
        critique = None
        if self.critic is not None:
            critique = self.critic.review(
                intervention=arm.intervention,
                discount=arm.discount_percentage,
                rationale=rationale,
                features=features,
                customer=customer,
                calibrated=calibrated,
                exploring=selection.exploring,
            )
            if critique.intervened:
                intervention, discount = self.critic.apply(
                    critique, arm.intervention, arm.discount_percentage
                )
                if critique.verdict == "SOFTEN":
                    self.stats.critic_softened += 1
                else:
                    self.stats.critic_rejected += 1
                arm = Arm(intervention, discount)
                rationale = f"{rationale} Critic: {critique.reason}"[:300]

        # Record the decision so the eventual outcome can be attributed to it.
        self._pending[case.id] = (features, arm, calibrated)

        evidence = [
            f"segment={features.segment}",
            f"rule_prior={features.prior_probability:.2f}",
            f"calibrated={calibrated:.2f}",
            f"bandit_arm={arm.id}",
            f"posterior_mean={selection.posterior_mean:.2f}",
            f"observations={selection.pulls}",
            f"exploring={selection.exploring}",
        ]
        if self.propensity.updates:
            evidence.append(f"calibration={self.propensity.explain(features)}")
        if critique is not None:
            evidence.append(f"critic={critique.verdict}:{critique.code}")

        expected = case.revenue_at_risk.scaled(
            calibrated * max(0.0, 1.0 - arm.discount_percentage / 100.0)
        )
        return InterventionPlan(
            intervention=arm.intervention,
            discount_percentage=arm.discount_percentage,
            contact_customer=arm.contacts_customer,
            rationale=rationale[:300],
            produced_by=self.actor,
            is_llm_output=used_llm,
            evidence=evidence,
            alternatives_considered=alternatives,
            expected_recovery_value=expected,
            confidence=(
                confidence if confidence is not None else diagnosis.confidence
            ),
        )

    # -- learning -----------------------------------------------------------

    def observe_outcome(self, case_id: str, recovered: bool) -> None:
        """Attribute a verified outcome to the decision that caused it.

        Idempotent and safe to call for a case that has no pending decision,
        which matters because the caller cannot always know whether a decision
        is outstanding. That property is load-bearing: an earlier version of the
        evaluation loop only reported outcomes for cases that reached a payment
        attempt, which silently censored ESCALATION and STOP -- the bandit could
        pick them, the case would end, and no update would ever arrive. Their
        posteriors stayed at the optimistic prior and ESCALATION pulls grew an
        order of magnitude while recovery fell. Any caller that terminates a case
        should call this unconditionally.
        """
        pending = self._pending.pop(case_id, None)
        if pending is None:
            return

        features, arm, calibrated = pending
        self.bandit.update(features.segment, arm, recovered)
        self.propensity.update(features, recovered)
        self.memory.remember(
            case_id=case_id,
            features=features,
            arm_id=arm.id,
            recovered=recovered,
            predicted_probability=calibrated,
        )
        self.stats.outcomes_learned += 1

    def pending_case_ids(self) -> list[str]:
        return list(self._pending)

    def calibration_pairs(self) -> tuple[list[float], list[bool]]:
        """(calibrated prediction, verified outcome) pairs for scoring."""
        return self.memory.calibration_pairs()

    # -- introspection ------------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "agent": self.name,
            "prompt": self.prompt.ref,
            "llm_provider": getattr(self.llm, "name", "none"),
            "decides_with": "contextual bandit over verified outcomes",
            "llm_role": "narration and downward-only dissent; never the decider",
            "stats": self.stats.to_dict(),
            "bandit": self.bandit.snapshot(),
            "propensity": self.propensity.snapshot(),
            "memory": self.memory.snapshot(),
            "critic": self.critic.snapshot() if self.critic else None,
        }

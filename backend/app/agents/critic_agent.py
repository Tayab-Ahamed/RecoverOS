"""An adversarial reviewer sitting between the planner and the policy engine.

Why a second agent instead of more rules in the first
-----------------------------------------------------
The planner is an optimiser: it is trying to maximise expected recovered value,
and every one of its failure modes points the same direction -- contact more
people, discount more often, keep working a dead case. Adding restraint to the
same component that is being rewarded for aggression means the restraint is
always the thing that gets tuned away.

So restraint gets its own component, with its own objective and a structurally
limited action space. The critic can only ever make an action *less* aggressive.
That is enforced by `AGGRESSION` and is the property that makes it safe to let a
language model participate at all: a compromised, confused or injected critic can
stop a case or downgrade a link to a reminder, and that is the entire blast
radius. It cannot escalate, cannot raise a discount, cannot approve anything.

How it differs from the policy engine
-------------------------------------
The policy engine answers "is this permitted?" -- deterministic, versioned,
checksummed, and the actual authority. The critic answers "is this *wise*?",
which is a judgement about expected value, contact fatigue and evidence quality
that cannot be expressed as a static rule table. The critic runs first and is
advisory; the policy engine still authorises everything afterwards. Nothing here
can widen what the policy engine allows.

Hard checks run before the model
--------------------------------
The four deterministic checks in `_hard_checks` are the ones with real money
behind them, and they do not depend on a model being available, configured or
correct. The LLM is consulted only when the hard checks pass, and its verdict is
validated and aggression-clamped before use. With no LLM configured the critic
still works -- it just stops offering prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents import guardrails, prompts
from app.agents.features import CaseFeatures
from app.agents.llm import LLMError
from app.agents.memory import OutcomeMemory
from app.domain.entities import Customer, InterventionType

# Ordering of actions by how much they impose on the customer. The critic may
# only move an action to a strictly lower value. This single mapping is what
# bounds the blast radius of a misbehaving critic.
AGGRESSION: dict[InterventionType, int] = {
    InterventionType.STOP: 0,
    InterventionType.ESCALATION: 1,
    InterventionType.REMINDER: 2,
    InterventionType.SUBSCRIPTION_RECOVERY: 3,
    InterventionType.PAYMENT_LINK: 4,
}

# Below this expected value, a customer contact is not worth spending. The
# policy engine enforces a floor on case value; this is about the *contact*
# budget, which is scarcer and is what actually degrades with overuse.
MIN_WORTHWHILE_EXPECTED_PAISE = 5_000

# A discount above this calibrated probability is margin given away on a case
# that was likely to convert anyway.
DISCOUNT_UNNECESSARY_ABOVE = 0.70


@dataclass(frozen=True)
class Critique:
    """One review."""

    verdict: str  # ACCEPT | SOFTEN | REJECT
    reason: str
    suggested_intervention: InterventionType | None = None
    code: str = ""
    from_model: bool = False
    confidence: float = 0.0

    @property
    def intervened(self) -> bool:
        return self.verdict != "ACCEPT"

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "suggested": (
                str(self.suggested_intervention)
                if self.suggested_intervention
                else None
            ),
            "code": self.code,
            "from_model": self.from_model,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class CriticStats:
    reviews: int = 0
    accepted: int = 0
    softened: int = 0
    rejected: int = 0
    llm_reviews: int = 0
    llm_failures: int = 0
    guardrail_blocks: int = 0
    upgrade_attempts_blocked: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    @property
    def intervention_rate(self) -> float:
        if not self.reviews:
            return 0.0
        return round((self.softened + self.rejected) / self.reviews, 4)

    def to_dict(self) -> dict:
        return {
            "reviews": self.reviews,
            "accepted": self.accepted,
            "softened": self.softened,
            "rejected": self.rejected,
            "intervention_rate": self.intervention_rate,
            "llm_reviews": self.llm_reviews,
            "llm_failures": self.llm_failures,
            "guardrail_blocks": self.guardrail_blocks,
            "upgrade_attempts_blocked": self.upgrade_attempts_blocked,
            "reasons": dict(sorted(self.reasons.items())),
        }


class CriticAgent:
    """Reviews a proposed action and may only soften or reject it."""

    name = "critic"

    def __init__(self, llm=None, memory: OutcomeMemory | None = None) -> None:
        self.llm = llm
        self.memory = memory
        self.stats = CriticStats()
        self.prompt = prompts.active("critic")

    # -- deterministic checks -----------------------------------------------

    def _hard_checks(
        self,
        intervention: InterventionType,
        discount: float,
        features: CaseFeatures,
        customer: Customer,
        calibrated: float,
        exploring: bool = False,
    ) -> Critique | None:
        """The objections that do not need a model. Ordered by severity.

        `exploring` suppresses the evidence-based objection only. When the
        bandit is deliberately sampling an arm to learn about it, overriding
        that choice on the grounds that current evidence favours another arm is
        self-defeating: it guarantees the sampled arm never accumulates the
        evidence that would justify it, so whichever arm happened to lead first
        stays ahead forever. The safety objections are never suppressed.
        """
        contacts = intervention not in (
            InterventionType.STOP,
            InterventionType.ESCALATION,
        )

        # Consent. Should be impossible upstream; checked anyway, because the
        # cost of being wrong here is a compliance incident, not a lost rupee.
        if customer.opted_out and contacts:
            return Critique(
                verdict="REJECT",
                reason=(
                    "Customer has opted out of contact; no recovery value "
                    "justifies contacting them."
                ),
                suggested_intervention=InterventionType.STOP,
                code="contacting_opted_out_customer",
            )

        expected = calibrated * features.amount_paise
        if contacts and expected < MIN_WORTHWHILE_EXPECTED_PAISE:
            return Critique(
                verdict="REJECT",
                reason=(
                    f"Expected recovery of Rs {expected / 100:.2f} does not "
                    f"justify spending a customer contact."
                ),
                suggested_intervention=InterventionType.STOP,
                code="expected_value_below_contact_cost",
            )

        # There is deliberately NO contact-fatigue check here.
        #
        # An earlier version softened any action where the customer already had
        # two contacts in the window. It looked prudent and was measured to be
        # the single worst decision in the system: it fired on 985 of 1287
        # reviews (77%), rewrote almost every PAYMENT_LINK to a REMINDER, and
        # dropped optimal-action rate from 69.6% to 32.5%. The learner lost to
        # the rulebook by 26 points, and the cause was not the learner.
        #
        # The reason it was wrong is that PolicyRules.max_customer_contacts
        # already caps contacts at two, and the policy engine is the authority
        # that enforces it. The check was not adding a safeguard, it was
        # duplicating one -- and because the critic runs on every decision, the
        # duplicate silently became the decision-maker while the bandit's
        # ranking was discarded.
        #
        # The lesson kept here on purpose: a component that can only make
        # things safer is not automatically safe to add. Overriding a correct
        # decision has a cost, and if that cost is never measured, a redundant
        # guardrail is indistinguishable from a broken one. Contact ceilings
        # belong to the policy engine; the economic question of whether a
        # permitted contact is *worth* spending is handled by the expected-value
        # check above, which fires on 148 reviews rather than 985.

        if discount > 0 and calibrated >= DISCOUNT_UNNECESSARY_ABOVE:
            return Critique(
                verdict="SOFTEN",
                reason=(
                    f"Calibrated recovery probability is {calibrated:.0%}; a "
                    f"{discount:g}% discount gives away margin unnecessarily."
                ),
                suggested_intervention=intervention,
                code="unnecessary_discount",
            )

        # Evidence-based objection: only raised where the sample is large
        # enough to mean something.
        if self.memory is not None and contacts and not exploring:
            found = self.memory.best_known_arm(features.segment)
            if found is not None:
                best_id, preferred = found
                stats = self.memory.segment_stats(features.segment)
                proposed = stats.get(str(intervention))
                if (
                    not best_id.startswith(str(intervention))
                    and proposed is not None
                    and proposed.attempts >= self.memory.min_confident_samples
                    and proposed.value_rate < preferred.value_rate * 0.7
                ):
                    return Critique(
                        verdict="SOFTEN",
                        reason=(
                            f"Verified history for {features.segment} favours "
                            f"{best_id} at {preferred.value_rate:.0%} value "
                            f"rate versus {proposed.value_rate:.0%} for "
                            f"{intervention}."
                        ),
                        suggested_intervention=InterventionType.REMINDER,
                        code="contradicted_by_verified_history",
                    )

        return None

    # -- model review -------------------------------------------------------

    def _build_prompt(
        self,
        intervention: InterventionType,
        discount: float,
        rationale: str,
        features: CaseFeatures,
        calibrated: float,
    ) -> str:
        history = (
            self.memory.recall_brief(features)
            if self.memory is not None
            else "No verified history available."
        )
        return (
            f"Failure reason: {features.reason}\n"
            f"Event type: {features.event_type}\n"
            f"Amount at risk: Rs {features.amount_paise / 100:.2f}\n"
            f"Attempt number: {features.attempt}\n"
            f"Contacts this window: {features.prior_contacts_in_window}\n"
            f"Customer value band: {features.ltv_band}\n"
            f"Rule-based prior: {features.prior_probability:.2f}\n"
            f"Calibrated probability: {calibrated:.2f}\n"
            f"Verified history: {history}\n"
            f"Proposed action: {intervention}\n"
            f"Proposed discount: {discount:g}%\n"
            f"Planner rationale: {rationale}\n"
        )

    def _model_review(
        self,
        intervention: InterventionType,
        discount: float,
        rationale: str,
        features: CaseFeatures,
        calibrated: float,
    ) -> Critique | None:
        if self.llm is None or getattr(self.llm, "name", "") == "deterministic":
            return None

        self.stats.llm_reviews += 1
        try:
            raw = self.llm.complete_json(
                system=self.prompt.system,
                prompt=self._build_prompt(
                    intervention, discount, rationale, features, calibrated
                ),
                schema_hint=self.prompt.schema_hint,
            )
        except LLMError:
            self.stats.llm_failures += 1
            return None

        result = guardrails.validate_critique(raw)
        if not result.ok:
            self.stats.guardrail_blocks += 1
            for code in result.codes:
                self.stats.reasons[f"blocked:{code}"] = (
                    self.stats.reasons.get(f"blocked:{code}", 0) + 1
                )
            return None

        payload = result.payload
        verdict = payload["verdict"]
        if verdict == "ACCEPT":
            return None

        suggested = payload["suggested_intervention"]
        if verdict == "REJECT":
            suggested = InterventionType.STOP
        elif suggested is None:
            suggested = InterventionType.REMINDER

        # The ceiling. A critic asking for a more aggressive action is either
        # confused or has been injected; either way it is refused and counted.
        if AGGRESSION.get(suggested, 99) >= AGGRESSION.get(intervention, 0):
            self.stats.upgrade_attempts_blocked += 1
            self.stats.reasons["blocked:critic_tried_to_escalate"] = (
                self.stats.reasons.get("blocked:critic_tried_to_escalate", 0) + 1
            )
            return None

        return Critique(
            verdict=verdict,
            reason=payload["reason"],
            suggested_intervention=suggested,
            code="model_review",
            from_model=True,
            confidence=payload["confidence"],
        )

    # -- entry point --------------------------------------------------------

    def review(
        self,
        intervention: InterventionType,
        discount: float,
        rationale: str,
        features: CaseFeatures,
        customer: Customer,
        calibrated: float,
        exploring: bool = False,
    ) -> Critique:
        """Review one proposed action. Deterministic checks take precedence."""
        self.stats.reviews += 1

        critique = self._hard_checks(
            intervention, discount, features, customer, calibrated, exploring
        )
        if critique is None:
            critique = self._model_review(
                intervention, discount, rationale, features, calibrated
            )
        if critique is None:
            critique = Critique(
                verdict="ACCEPT",
                reason="No objection: action is proportionate to the evidence.",
                code="accepted",
            )

        self._tally(critique)
        return critique

    def _tally(self, critique: Critique) -> None:
        if critique.verdict == "ACCEPT":
            self.stats.accepted += 1
        elif critique.verdict == "SOFTEN":
            self.stats.softened += 1
        else:
            self.stats.rejected += 1
        if critique.code:
            self.stats.reasons[critique.code] = (
                self.stats.reasons.get(critique.code, 0) + 1
            )

    def apply(
        self,
        critique: Critique,
        intervention: InterventionType,
        discount: float,
    ) -> tuple[InterventionType, float]:
        """Apply a critique, enforcing the aggression ceiling once more.

        Re-checked here rather than trusted from `review` so that the invariant
        holds even if a future caller constructs a `Critique` directly. Cheap,
        and it is the one guarantee this module exists to provide.
        """
        if critique.verdict == "ACCEPT":
            return intervention, discount

        if critique.verdict == "REJECT":
            return InterventionType.STOP, 0.0

        suggested = critique.suggested_intervention or intervention
        if AGGRESSION.get(suggested, 99) > AGGRESSION.get(intervention, 0):
            self.stats.upgrade_attempts_blocked += 1
            return intervention, discount

        # A softened action never keeps a discount it did not justify.
        if suggested is intervention and critique.code == "unnecessary_discount":
            return intervention, 0.0
        return suggested, 0.0

    def snapshot(self) -> dict:
        return {
            "agent": self.name,
            "prompt": self.prompt.ref,
            "llm_provider": getattr(self.llm, "name", "none"),
            "action_space": "may only reduce aggression; never escalate",
            "aggression_order": [
                str(k) for k in sorted(AGGRESSION, key=lambda i: AGGRESSION[i])
            ],
            "stats": self.stats.to_dict(),
        }

"""Benchmark harness and invariant auditor.

This is where the headline number comes from. It runs the full loop over a
dataset, drives simulated provider callbacks through the real signed-webhook
path, and then audits the resulting audit log against the five invariants. A
violation fails the run rather than being reported as a warning.

What changed, and why it matters
--------------------------------
The first version of this harness decided whether a customer paid by sampling
against `case.diagnosis.recovery_probability` -- the agent's own prediction.
That made the benchmark circular. The agent could not be wrong, because its
belief *was* the world; a confident agent scored well by being confident, and
the measured "lift" over the fixed baseline came from retry branching rather
than from better decisions.

Outcomes now come from `app.evaluation.ground_truth`, a hidden conversion model
with base rates deliberately different from the agent's priors, a best action
that varies by failure cause and attempt index, and latent per-customer
heterogeneity nothing can observe. The agent can now be wrong, so:

- calibration error is a real measurement rather than zero by construction,
- action choice has a cost, so a learner can beat a rulebook on merit,
- and no strategy can reach 100%, because part of the variance is unknowable.

`scripts/static_check.py` fails the build if any module under `app.agents`,
`app.detection` or `app.policies` imports the ground-truth model. The reasoning
layer provably cannot read its own answer key.

The arms
--------
- `fixed_baseline`  payment link for everything. No adaptation.
- `recoveros`       the hand-written rulebook. The previous system.
- `learning`        contextual bandit + online propensity + critic.
- `learning_llm`    the same, with a language model narrating and dissenting.
- `oracle`          full knowledge of the hidden world. Not achievable; it
                    exists to put a ceiling on the scoreboard so every other
                    number can be read as a fraction of what was attainable.
- `ungoverned`      limits removed, to price what governance prevents.

Common random numbers are preserved across arms: the uniform draw for a case is
derived from the case reference alone, so two strategies meeting the same case
on the same attempt face identical luck and differ only in the quality of the
action they chose. Without this, arm-to-arm differences at this sample size
would be mostly noise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, UTC

from app.agents.critic_agent import CriticAgent
from app.agents.learning_strategist import LearningStrategistAgent
from app.agents.llm import InstrumentedLLMClient, ScriptedLLMClient
from app.agents.strategist_agent import StrategistAgent
from app.detection.rules import detect
from app.domain.entities import DataProvenance, InterventionType, RecoveryCase
from app.domain.money import Money
from app.domain.states import CaseState
from app.evaluation import calibration
from app.evaluation.generator import Dataset
from app.evaluation.ground_truth import GroundTruthWorld
from app.integrations.idempotency import InMemoryIdempotencyStore
from app.integrations.mock_razorpay import MockRazorpayProvider
from app.integrations.signature import compute_signature
from app.policies.config import PolicyRules, PolicyVersion
from app.policies.engine import PolicyEngine
from app.services.audit import AuditLog
from app.services.executor import RecoveryExecutor
from app.services.orchestrator import RecoveryOrchestrator
from app.services.state_machine import StateMachine
from app.services.verifier import OutcomeVerifier
from app.webhooks.handler import WebhookHandler

WEBHOOK_SECRET = "benchmark_secret"

# The governed ruleset is the yardstick for compliance in every strategy,
# including the ungoverned baseline. Otherwise a strategy could "comply" simply
# by having no rules.
GOVERNED_RULES = PolicyRules()

STRATEGIES: tuple[str, ...] = (
    "fixed_baseline",
    "recoveros",
    "learning",
    "learning_llm",
    "oracle",
    "ungoverned",
)


class FixedBaselineStrategist:
    """A deliberately simple baseline for measuring adaptive planning value."""

    name = "fixed_baseline"

    def plan(self, case, diagnosis, customer):
        from app.domain.entities import InterventionPlan
        from app.domain.states import Actor

        if customer.opted_out:
            intervention = InterventionType.STOP
            contact = False
        else:
            intervention = InterventionType.PAYMENT_LINK
            contact = True
        expected = case.revenue_at_risk.scaled(diagnosis.recovery_probability)
        return InterventionPlan(
            intervention=intervention,
            discount_percentage=0.0,
            contact_customer=contact,
            rationale="Fixed baseline: payment link for every eligible case; no adaptive reasoning.",
            produced_by=Actor.STRATEGIST_AGENT,
            is_llm_output=False,
            evidence=["fixed baseline", f"reason={case.event.reason}"],
            alternatives_considered=["PAYMENT_LINK"],
            expected_recovery_value=expected,
            confidence=diagnosis.confidence,
        )


class OracleStrategist:
    """Chooses the value-maximising action using the hidden world model.

    This is not an agent and is not achievable in production. It is the ceiling.
    Reporting a learner's score without a ceiling invites the reader to assume
    the remaining gap is small; publishing the oracle removes that ambiguity and
    is the reason this harness can claim the learner captured a specific
    fraction of available value rather than just "more than baseline".
    """

    name = "oracle"

    def __init__(self, world: GroundTruthWorld, max_discount: float = 5.0) -> None:
        self.world = world
        self.max_discount = max_discount

    def plan(self, case, diagnosis, customer):
        from app.domain.entities import InterventionPlan
        from app.domain.states import Actor

        if customer.opted_out:
            intervention, discount = InterventionType.STOP, 0.0
            probability = 0.0
        else:
            intervention, discount, _ = self.world.best_action(
                case.event,
                customer,
                attempt=case.attempts,
                contacts_before=customer.contacts_this_window,
                allowed_discounts=(0.0, self.max_discount),
            )
            probability = self.world.true_probability(
                case.event,
                customer,
                intervention,
                discount,
                case.attempts,
                customer.contacts_this_window,
            )

        expected = case.revenue_at_risk.scaled(
            probability * max(0.0, 1.0 - discount / 100.0)
        )
        return InterventionPlan(
            intervention=intervention,
            discount_percentage=discount,
            contact_customer=intervention
            not in {InterventionType.ESCALATION, InterventionType.STOP},
            rationale=(
                "Oracle: value-maximising action under full knowledge of the "
                "hidden conversion model. Upper bound, not achievable."
            ),
            produced_by=Actor.STRATEGIST_AGENT,
            is_llm_output=False,
            evidence=["oracle", f"true_probability={probability:.4f}"],
            alternatives_considered=["all arms evaluated against ground truth"],
            expected_recovery_value=expected,
            confidence=1.0,
        )


@dataclass
class RunMetrics:
    strategy: str
    dataset_run_id: str
    provenance: str
    cases: int = 0
    eligible_cases: int = 0
    revenue_at_risk: int = 0
    eligible_revenue: int = 0
    recovered_revenue: int = 0
    recovered_cases: int = 0
    denied_cases: int = 0
    escalated_cases: int = 0
    awaiting_approval: int = 0
    ineligible_cases: int = 0
    contacts_made: int = 0
    provider_calls: int = 0
    webhooks_processed: int = 0
    webhooks_rejected: int = 0
    duplicate_webhooks_ignored: int = 0
    audit_records: int = 0
    strategy_mix: dict[str, int] = field(default_factory=dict)
    adaptive_explanations: int = 0
    violations: list[str] = field(default_factory=list)

    # -- decision-quality measurement (new) --
    decisions: int = 0
    total_regret_paise: float = 0.0
    optimal_actions: int = 0
    predictions: list[float] = field(default_factory=list)
    outcomes: list[bool] = field(default_factory=list)
    true_probabilities: list[float] = field(default_factory=list)
    agent_snapshot: dict = field(default_factory=dict)
    llm_telemetry: dict = field(default_factory=dict)

    @property
    def recovery_rate(self) -> float:
        if self.eligible_revenue == 0:
            return 0.0
        return round(self.recovered_revenue / self.eligible_revenue, 4)

    @property
    def policy_violation_rate(self) -> float:
        if self.cases == 0:
            return 0.0
        return round(len(self.violations) / self.cases, 6)

    @property
    def optimal_action_rate(self) -> float:
        if self.decisions == 0:
            return 0.0
        return round(self.optimal_actions / self.decisions, 4)

    @property
    def mean_regret_paise(self) -> float:
        if self.decisions == 0:
            return 0.0
        return round(self.total_regret_paise / self.decisions, 2)

    def calibration_report(self) -> calibration.CalibrationReport:
        """How good the agent's stated probabilities actually were."""
        return calibration.score(self.strategy, self.predictions, self.outcomes)

    def to_dict(self) -> dict:
        report = self.calibration_report()
        return {
            "strategy": self.strategy,
            "dataset_run_id": self.dataset_run_id,
            "provenance": self.provenance,
            "cases": self.cases,
            "eligible_cases": self.eligible_cases,
            "revenue_at_risk_paise": self.revenue_at_risk,
            "eligible_revenue_paise": self.eligible_revenue,
            "recovered_revenue_paise": self.recovered_revenue,
            "revenue_at_risk_rupees": Money(self.revenue_at_risk).rupees_str,
            "recovered_revenue_rupees": Money(self.recovered_revenue).rupees_str,
            "recovered_cases": self.recovered_cases,
            "recovery_rate": self.recovery_rate,
            "denied_cases": self.denied_cases,
            "escalated_cases": self.escalated_cases,
            "awaiting_approval": self.awaiting_approval,
            "ineligible_cases": self.ineligible_cases,
            "contacts_made": self.contacts_made,
            "provider_calls": self.provider_calls,
            "webhooks_processed": self.webhooks_processed,
            "webhooks_rejected": self.webhooks_rejected,
            "duplicate_webhooks_ignored": self.duplicate_webhooks_ignored,
            "audit_records": self.audit_records,
            "strategy_mix": self.strategy_mix,
            "adaptive_explanations": self.adaptive_explanations,
            "recovery_per_contact_paise": (
                round(self.recovered_revenue / self.contacts_made, 2)
                if self.contacts_made
                else 0.0
            ),
            "policy_violations": len(self.violations),
            "policy_violation_rate": self.policy_violation_rate,
            # decision quality
            "decisions_scored": self.decisions,
            "optimal_action_rate": self.optimal_action_rate,
            "mean_regret_paise": self.mean_regret_paise,
            "total_regret_rupees": round(self.total_regret_paise / 100.0, 2),
            "calibration": report.to_dict(),
            "agent": self.agent_snapshot,
            "llm": self.llm_telemetry,
        }


def _audit_invariants(
    cases: list[RecoveryCase],
    customers: dict,
    audit: AuditLog,
) -> list[str]:
    """Check the five invariants against the governed ruleset."""
    violations: list[str] = []

    for case in cases:
        # Invariant 1: no RECOVERED without verified captured payment evidence.
        if case.state is CaseState.RECOVERED:
            if case.evidence is None or not case.evidence.captured:
                violations.append(f"{case.id}: RECOVERED without captured evidence")
            elif case.recovered_amount != case.evidence.amount:
                violations.append(f"{case.id}: recovered amount disagrees with evidence")

        # Invariant 2: no outbound action without an affirmative decision.
        records = audit.for_case(case.id)
        actions = [r for r in records if r.action == "PAYMENT_LINK_CREATED"]
        for record in actions:
            if not record.decision_id or not record.policy_version_id:
                violations.append(f"{case.id}: action without decision or policy version")

        # Invariant 3: attempt ceiling respected.
        if case.attempts > GOVERNED_RULES.max_recovery_attempts:
            violations.append(
                f"{case.id}: {case.attempts} attempts exceeds "
                f"{GOVERNED_RULES.max_recovery_attempts}"
            )

        # Invariant 3b: contact ceiling respected.
        if case.contacts_made > GOVERNED_RULES.max_customer_contacts:
            violations.append(
                f"{case.id}: {case.contacts_made} contacts exceeds "
                f"{GOVERNED_RULES.max_customer_contacts}"
            )

        # Invariant 4: opted-out customers are never contacted.
        customer = customers.get(case.customer_id)
        if customer is not None and customer.opted_out and actions:
            violations.append(f"{case.id}: contacted an opted-out customer")

        # Economic floor respected.
        if actions and case.revenue_at_risk < GOVERNED_RULES.min_recovery_value:
            violations.append(f"{case.id}: acted below the economic floor")

        # Invariant 5: every case that did anything has an audit trail.
        if not records:
            violations.append(f"{case.id}: no audit records")

    return violations


# Fixed reference time for all evaluation runs, matching the dataset generator's
# default `now`. Mid-day UTC sits inside the default contact window, so the
# time-of-day rule does not suppress the batch.
EVAL_CLOCK_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)


def _build_strategist(strategy: str, seed: str, world: GroundTruthWorld):
    """Construct the decision layer for one arm.

    Returns (strategist, rules, llm_client).
    """
    if strategy == "recoveros":
        return StrategistAgent(), GOVERNED_RULES, None

    if strategy == "fixed_baseline":
        return FixedBaselineStrategist(), GOVERNED_RULES, None

    if strategy == "oracle":
        return OracleStrategist(world), GOVERNED_RULES, None

    if strategy == "learning":
        # No language model: isolates the contribution of the learning
        # components, so any lift cannot be attributed to the LLM.
        return (
            LearningStrategistAgent(llm=None, seed=seed, use_critic=True),
            GOVERNED_RULES,
            None,
        )

    if strategy == "learning_llm":
        # Scripted client: deterministic, offline, and injects malformed and
        # prompt-injected responses at a fixed rate so the guardrail catch rate
        # in the report is measured against known-bad input.
        llm = InstrumentedLLMClient(
            inner=ScriptedLLMClient(seed=seed), model="scripted"
        )
        agent = LearningStrategistAgent(
            llm=llm,
            seed=seed,
            critic=CriticAgent(llm=llm),
            use_critic=True,
        )
        agent.critic.memory = agent.memory
        return agent, GOVERNED_RULES, llm

    if strategy == "ungoverned":
        return (
            FixedBaselineStrategist(),
            PolicyRules(
                max_recovery_attempts=99,
                max_customer_contacts=99,
                min_recovery_value_paise=0,
                max_discount_percentage=100.0,
                stop_after_opt_out=False,
                require_approval_above_threshold=False,
            ),
            None,
        )

    raise ValueError(f"unknown strategy {strategy}")


def run_strategy(
    dataset: Dataset,
    strategy: str = "recoveros",
    seed: str = "bench",
    auto_approve: bool = True,
    world_seed: str = "world_v1",
) -> tuple[RunMetrics, list[RecoveryCase], AuditLog]:
    """Run one strategy end to end over a dataset.

    Outcomes are drawn from the hidden ground-truth world, not from the agent's
    own predictions. The world seed is fixed across arms so that comparisons are
    paired.
    """
    world = GroundTruthWorld(seed=world_seed)
    strategist, rules, llm = _build_strategist(strategy, seed, world)

    audit = AuditLog()
    sm = StateMachine(audit)
    provider = MockRazorpayProvider(seed=seed)
    executor = RecoveryExecutor(provider, sm, audit)
    policy = PolicyEngine(
        PolicyVersion(id=f"{strategy}_v1", rules=rules),
        # Pin the clock. The contact-time-window rule reads the current hour, so
        # a wall-clock engine would make the published benchmark depend on when
        # it was run: executed at 03:00 UTC every contact is denied and the
        # numbers quietly change. This matches the generator's fixed reference
        # time, so a run is a function of code and seed alone.
        clock=lambda: EVAL_CLOCK_NOW,
    )
    verifier = OutcomeVerifier(sm, audit)
    idempotency = InMemoryIdempotencyStore()

    cases_by_ref: dict[str, RecoveryCase] = {}
    handler = WebhookHandler(
        secret=WEBHOOK_SECRET,
        verifier=verifier,
        idempotency=idempotency,
        case_lookup=cases_by_ref.get,
    )

    orchestrator = RecoveryOrchestrator(
        policy=policy,
        executor=executor,
        state_machine=sm,
        audit=audit,
        strategist=strategist,
        approver=(lambda case, decision: True) if auto_approve else None,
    )

    metrics = RunMetrics(
        strategy=strategy,
        dataset_run_id=dataset.run_id,
        provenance=str(DataProvenance.SYNTHETIC),
    )

    learns = hasattr(strategist, "observe_outcome")

    signals = detect(dataset.events, dataset.customers, dataset.generated_at)
    all_cases: list[RecoveryCase] = []

    for signal in signals:
        customer = dataset.customers[signal.event.customer_id]
        case = orchestrator.open_case(
            signal, DataProvenance.SYNTHETIC, dataset.run_id
        )
        cases_by_ref[case.id] = case
        all_cases.append(case)
        orchestrator.advance(case, customer)

        # Record the selected intervention so the benchmark measures what the
        # planner actually chose, not only the final payment outcome.
        if case.plan is not None:
            key = str(case.plan.intervention)
            metrics.strategy_mix[key] = metrics.strategy_mix.get(key, 0) + 1
            if case.plan.intervention is not InterventionType.PAYMENT_LINK:
                metrics.adaptive_explanations += 1

        # ---- VERIFY: drive provider callbacks through the real signed path ----
        attempt = 0
        while case.state is CaseState.AWAITING_PAYMENT:
            attempt += 1
            assert case.diagnosis is not None
            assert case.plan is not None

            attempt_index = attempt - 1
            contacts_before = max(0, case.contacts_made - 1)

            # The hidden world decides, based on the action actually taken.
            outcome = world.draw(
                reference_id=f"{case.event.id}:{attempt}",
                event=case.event,
                customer=customer,
                intervention=case.plan.intervention,
                discount_percentage=case.plan.discount_percentage,
                attempt=attempt_index,
                contacts_before=contacts_before,
            )

            # Score the decision itself, independently of luck.
            best_arm, best_discount, _ = world.best_action(
                case.event, customer, attempt_index, contacts_before
            )
            metrics.decisions += 1
            metrics.total_regret_paise += world.regret(
                case.event,
                customer,
                case.plan.intervention,
                case.plan.discount_percentage,
                attempt_index,
                contacts_before,
            )
            if case.plan.intervention is best_arm:
                metrics.optimal_actions += 1

            # Calibration: what the agent claimed, against what happened.
            metrics.predictions.append(case.diagnosis.recovery_probability)
            metrics.outcomes.append(outcome.will_pay)
            metrics.true_probabilities.append(outcome.true_probability)

            assert case.external_link_id is not None
            event = (
                provider.paid_event(case.external_link_id)
                if outcome.will_pay
                else provider.failed_event(case.external_link_id)
            )
            raw = json.dumps(event).encode()
            sig = compute_signature(raw, WEBHOOK_SECRET)
            event_id = f"evt_{case.id}_{attempt}"
            result = handler.handle(raw, sig, event_id)
            if result.accepted:
                metrics.webhooks_processed += 1
            else:
                metrics.webhooks_rejected += 1

            # Replay the same event to prove idempotency on the real path.
            replay = handler.handle(raw, sig, event_id)
            if not replay.accepted and replay.reason == "duplicate event ignored":
                metrics.duplicate_webhooks_ignored += 1

            # Learn only from the verified provider outcome.
            if learns:
                strategist.observe_outcome(case.id, outcome.will_pay)

            if case.state is CaseState.FAILED:
                orchestrator.handle_failure(case, customer)

        # Censoring correction. ESCALATION and STOP end a case without ever
        # reaching a payment attempt, so the loop above never draws an outcome
        # for them and never reports one. Left uncorrected, those arms can only
        # ever accumulate optimism: the bandit picks ESCALATION, the case dies
        # quietly, no failure is attributed, and the posterior never moves. The
        # observed effect was a learner that got monotonically worse with more
        # data (ESCALATION pulls 59 -> 736 between the 200- and 2000-case runs)
        # while its recovery rate fell to 34%. Any decision still pending when
        # the case terminates is therefore attributed its true outcome, which
        # for a non-recovered terminal state is a failure. observe_outcome is
        # idempotent, so this is a no-op when the webhook path already resolved.
        if learns:
            strategist.observe_outcome(case.id, case.state is CaseState.RECOVERED)

    # ---- aggregate ----
    for case in all_cases:
        metrics.cases += 1
        metrics.revenue_at_risk += case.revenue_at_risk.paise
        metrics.contacts_made += case.contacts_made
        if case.state is CaseState.INELIGIBLE:
            metrics.ineligible_cases += 1
        else:
            metrics.eligible_cases += 1
            metrics.eligible_revenue += case.revenue_at_risk.paise
        if case.state is CaseState.RECOVERED:
            metrics.recovered_cases += 1
            assert case.recovered_amount is not None
            metrics.recovered_revenue += case.recovered_amount.paise
        elif case.state is CaseState.STOPPED:
            metrics.denied_cases += 1
        elif case.state is CaseState.ESCALATED:
            metrics.escalated_cases += 1
        elif case.state is CaseState.AWAITING_APPROVAL:
            metrics.awaiting_approval += 1

    metrics.provider_calls = provider.create_calls
    metrics.audit_records = len(audit)
    metrics.violations = _audit_invariants(all_cases, dataset.customers, audit)

    if hasattr(strategist, "snapshot"):
        metrics.agent_snapshot = strategist.snapshot()
    if llm is not None:
        metrics.llm_telemetry = llm.telemetry.to_dict()
        inner = getattr(llm, "inner", None)
        injected = getattr(inner, "injected_faults", None)
        if injected:
            metrics.llm_telemetry["injected_faults"] = dict(sorted(injected.items()))

    return metrics, all_cases, audit


def compare(dataset: Dataset, strategies: tuple[str, ...] = STRATEGIES) -> dict:
    """Run every arm on one dataset and assemble the comparison report."""
    results: dict[str, RunMetrics] = {}
    for strategy in strategies:
        metrics, _, _ = run_strategy(dataset, strategy)
        results[strategy] = metrics

    baseline = results.get("fixed_baseline")
    rules_arm = results.get("recoveros")
    learner = results.get("learning")
    oracle = results.get("oracle")

    def per_contact(m: RunMetrics | None) -> float:
        if m is None or not m.contacts_made:
            return 0.0
        return round(m.recovered_revenue / m.contacts_made, 2)

    report: dict = {
        "dataset": {
            "run_id": dataset.run_id,
            "seed": dataset.seed,
            "events": len(dataset.events),
            "customers": len(dataset.customers),
            "provenance": str(DataProvenance.SYNTHETIC),
            "profile": dataset.profile,
        },
        "experimental_design": {
            "outcome_model": "app.evaluation.ground_truth.GroundTruthWorld",
            "hidden_from_agents": True,
            "enforced_by": "scripts/static_check.py forbids app.agents importing it",
            "paired_sampling": (
                "Common random numbers: the uniform draw depends only on the case "
                "reference, so all arms face identical luck on the same case."
            ),
            "note": (
                "Agent priors in app/detection/rules.py are deliberately "
                "miscalibrated against the true conversion rates, so calibration "
                "error is measurable rather than zero by construction."
            ),
        },
    }

    for name, metrics in results.items():
        report[name] = metrics.to_dict()

    # Backward-compatible aliases used by the API and existing artifacts.
    if rules_arm is not None:
        report["governed"] = rules_arm.to_dict()
        report["adaptive_agent"] = rules_arm.to_dict()

    if baseline is not None and rules_arm is not None:
        report["ai_lift"] = {
            "recovered_revenue_delta_paise": (
                rules_arm.recovered_revenue - baseline.recovered_revenue
            ),
            "recovery_rate_delta": round(
                rules_arm.recovery_rate - baseline.recovery_rate, 4
            ),
            "contacts_delta": rules_arm.contacts_made - baseline.contacts_made,
            "recovery_per_contact_delta_paise": round(
                per_contact(rules_arm) - per_contact(baseline), 2
            ),
            "interpretation": (
                "rule-based planner versus fixed payment-link baseline; both use "
                "the same governed policy"
            ),
        }

    if learner is not None and rules_arm is not None:
        learning_lift: dict = {
            "recovered_revenue_delta_paise": (
                learner.recovered_revenue - rules_arm.recovered_revenue
            ),
            "recovery_rate_delta": round(
                learner.recovery_rate - rules_arm.recovery_rate, 4
            ),
            "contacts_delta": learner.contacts_made - rules_arm.contacts_made,
            "recovery_per_contact_delta_paise": round(
                per_contact(learner) - per_contact(rules_arm), 2
            ),
            "optimal_action_rate_delta": round(
                learner.optimal_action_rate - rules_arm.optimal_action_rate, 4
            ),
            "mean_regret_delta_paise": round(
                learner.mean_regret_paise - rules_arm.mean_regret_paise, 2
            ),
            "brier_skill_score_vs_rules": calibration.skill_score(
                learner.calibration_report(), rules_arm.calibration_report()
            ),
            "interpretation": (
                "learning agent versus the hand-written rulebook, same governed "
                "policy and same hidden world. Negative regret delta means the "
                "learner chose better actions."
            ),
        }
        if oracle is not None and oracle.recovered_revenue:
            learning_lift["share_of_attainable_value"] = {
                "learning": round(
                    learner.recovered_revenue / oracle.recovered_revenue, 4
                ),
                "rules": round(
                    rules_arm.recovered_revenue / oracle.recovered_revenue, 4
                ),
                "fixed_baseline": (
                    round(baseline.recovered_revenue / oracle.recovered_revenue, 4)
                    if baseline is not None
                    else None
                ),
                "note": (
                    "Fraction of the oracle's recovered revenue captured. The "
                    "oracle has full knowledge of the hidden world and is not "
                    "achievable; it bounds the scoreboard."
                ),
            }
        report["learning_lift"] = learning_lift

    return report

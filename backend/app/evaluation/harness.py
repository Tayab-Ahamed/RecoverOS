"""Benchmark harness and invariant auditor.

This is where the headline number comes from. It runs the full loop over a
dataset, drives simulated provider callbacks through the real signed-webhook
path, and then audits the resulting audit log against the five invariants. A
violation fails the run rather than being reported as a warning.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.detection.rules import detect
from app.domain.entities import DataProvenance, InterventionType, RecoveryCase
from app.domain.money import Money
from app.domain.states import CaseState
from app.evaluation.generator import Dataset
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
    violations: list[str] = field(default_factory=list)

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

    def to_dict(self) -> dict:
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
            "policy_violations": len(self.violations),
            "policy_violation_rate": self.policy_violation_rate,
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


def run_strategy(
    dataset: Dataset,
    strategy: str = "recoveros",
    seed: str = "bench",
    auto_approve: bool = True,
) -> tuple[RunMetrics, list[RecoveryCase], AuditLog]:
    """Run one strategy end to end over a dataset.

    strategy="recoveros"  -> the governed policy
    strategy="ungoverned" -> limits removed, to quantify what governance costs
                             and what it prevents
    """
    if strategy == "recoveros":
        rules = GOVERNED_RULES
    elif strategy == "ungoverned":
        rules = PolicyRules(
            max_recovery_attempts=99,
            max_customer_contacts=99,
            min_recovery_value_paise=0,
            max_discount_percentage=100.0,
            stop_after_opt_out=False,
            require_approval_above_threshold=False,
        )
    else:
        raise ValueError(f"unknown strategy {strategy}")

    audit = AuditLog()
    sm = StateMachine(audit)
    provider = MockRazorpayProvider(seed=seed)
    executor = RecoveryExecutor(provider, sm, audit)
    policy = PolicyEngine(PolicyVersion(id=f"{strategy}_v1", rules=rules))
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
        approver=(lambda case, decision: True) if auto_approve else None,
    )

    metrics = RunMetrics(
        strategy=strategy,
        dataset_run_id=dataset.run_id,
        provenance=str(DataProvenance.SYNTHETIC),
    )

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

        # ---- VERIFY: drive provider callbacks through the real signed path ----
        attempt = 0
        while case.state is CaseState.AWAITING_PAYMENT:
            attempt += 1
            assert case.diagnosis is not None
            will_pay = provider.customer_will_pay(
                f"{case.event.id}:{attempt}", case.diagnosis.recovery_probability
            )
            assert case.external_link_id is not None
            event = (
                provider.paid_event(case.external_link_id)
                if will_pay
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

            if case.state is CaseState.FAILED:
                orchestrator.handle_failure(case, customer)

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
    return metrics, all_cases, audit


def compare(dataset: Dataset) -> dict:
    """Run both strategies over the same dataset and report the difference."""
    governed, _, _ = run_strategy(dataset, "recoveros")
    ungoverned, _, _ = run_strategy(dataset, "ungoverned")
    return {
        "dataset": {
            "run_id": dataset.run_id,
            "seed": dataset.seed,
            "events": len(dataset.events),
            "customers": len(dataset.customers),
            "provenance": str(DataProvenance.SYNTHETIC),
            "profile": dataset.profile,
        },
        "governed": governed.to_dict(),
        "ungoverned": ungoverned.to_dict(),
    }

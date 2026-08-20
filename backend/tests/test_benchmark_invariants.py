import unittest

from app.evaluation.generator import generate
from app.evaluation.harness import run_strategy


class TestBenchmarkInvariants(unittest.TestCase):
    """The five invariants must hold across a full batch, not just per case.

    A governance claim proved on three demo cases is not a governance claim.
    """

    @classmethod
    def setUpClass(cls):
        cls.dataset = generate(n_events=2000, seed=42, profile="test")
        cls.metrics, cls.cases, cls.audit = run_strategy(cls.dataset, "recoveros")

    def test_zero_policy_violations_across_the_batch(self):
        self.assertEqual(
            self.metrics.violations, [], f"violations: {self.metrics.violations[:5]}"
        )
        self.assertEqual(self.metrics.policy_violation_rate, 0.0)

    def test_every_case_is_accounted_for(self):
        self.assertEqual(self.metrics.cases, len(self.dataset.events))

    def test_money_is_recovered(self):
        self.assertGreater(self.metrics.recovered_revenue, 0)
        self.assertGreater(self.metrics.recovered_cases, 0)

    def test_recovered_revenue_never_exceeds_revenue_at_risk(self):
        self.assertLessEqual(self.metrics.recovered_revenue, self.metrics.revenue_at_risk)

    def test_every_recovery_has_captured_evidence(self):
        from app.domain.states import CaseState

        for case in self.cases:
            if case.state is CaseState.RECOVERED:
                self.assertIsNotNone(case.evidence)
                self.assertTrue(case.evidence.captured)

    def test_every_provider_call_is_matched_by_an_audited_action(self):
        audited = [r for r in self.audit.all() if r.action == "PAYMENT_LINK_CREATED"]
        self.assertEqual(len(audited), self.metrics.provider_calls)

    def test_no_opted_out_customer_was_contacted(self):
        opted_out = {c.id for c in self.dataset.customers.values() if c.opted_out}
        for case in self.cases:
            if case.customer_id in opted_out:
                self.assertEqual(case.contacts_made, 0, f"{case.id} contacted")

    def test_every_duplicate_webhook_was_ignored(self):
        # Every delivered event was replayed once by the harness.
        self.assertEqual(
            self.metrics.duplicate_webhooks_ignored, self.metrics.webhooks_processed
        )

    def test_run_is_bit_for_bit_reproducible(self):
        # Risk R7: a benchmark that cannot be reproduced is not evidence.
        repeat, _, _ = run_strategy(
            generate(n_events=2000, seed=42, profile="test"), "recoveros"
        )
        self.assertEqual(repeat.to_dict(), self.metrics.to_dict())

    def test_a_different_seed_produces_different_results(self):
        other, _, _ = run_strategy(
            generate(n_events=2000, seed=99, profile="test"), "recoveros"
        )
        self.assertNotEqual(other.recovered_revenue, self.metrics.recovered_revenue)


class TestGovernanceCosts(unittest.TestCase):
    """Quantify what governance prevents, rather than asserting it is free."""

    @classmethod
    def setUpClass(cls):
        dataset = generate(n_events=2000, seed=42, profile="test")
        cls.governed, _, _ = run_strategy(dataset, "recoveros")
        cls.ungoverned, _, _ = run_strategy(dataset, "ungoverned")

    def test_removing_the_guard_produces_violations(self):
        # If this ever passes with zero violations, the auditor is not working.
        self.assertGreater(len(self.ungoverned.violations), 0)

    def test_governance_reduces_customer_contacts(self):
        self.assertLess(self.governed.contacts_made, self.ungoverned.contacts_made)

    def test_governance_is_the_only_run_with_a_clean_audit(self):
        self.assertEqual(len(self.governed.violations), 0)

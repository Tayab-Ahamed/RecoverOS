"""Tests for the counterfactual policy sandbox.

The sandbox makes a causal claim -- "this revenue difference is attributable to
the rule" -- and that claim is only true if the experiment is actually
controlled. These tests pin the properties the claim depends on:

- variants are audited against the governed ruleset, not their own, so a
  loosened variant cannot define away its violations;
- the consent breach is detected rather than rewarded, which is the one result
  that must never regress quietly;
- the sweep is deterministic, so a published curve reproduces;
- and the baseline is genuinely the shipped ruleset.
"""

from __future__ import annotations

import unittest

from app.evaluation.counterfactual import (
    PolicyVariant,
    default_variants,
    sweep,
)
from app.evaluation.generator import generate
from app.evaluation.harness import GOVERNED_RULES
from app.policies.config import PolicyRules

# Small but large enough to contain opted-out customers and low-value cases.
EVENTS = 150
SEED = 42


class CounterfactualCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = generate(n_events=EVENTS, seed=SEED, profile="benchmark")
        cls.result = sweep(cls.dataset)
        cls.by_name = {r.name: r for r in cls.result.results}


class TestExperimentIsControlled(CounterfactualCase):
    def test_every_default_variant_produced_a_row(self):
        self.assertEqual(len(self.result.results), len(default_variants()))

    def test_exactly_one_baseline(self):
        baselines = [r for r in self.result.results if r.is_baseline]
        self.assertEqual(len(baselines), 1)
        self.assertEqual(baselines[0].name, "governed_default")

    def test_baseline_uses_the_shipped_ruleset(self):
        """If the sandbox baseline drifts from GOVERNED_RULES the curve lies."""
        baseline = next(v for v in default_variants() if v.is_baseline)
        self.assertIs(baseline.rules, GOVERNED_RULES)

    def test_governed_baseline_has_no_violations(self):
        self.assertEqual(self.by_name["governed_default"].policy_violations, 0)

    def test_sweep_is_deterministic(self):
        """A published policy curve must reproduce from the same seed."""
        again = sweep(generate(n_events=EVENTS, seed=SEED, profile="benchmark"))
        for first, second in zip(self.result.results, again.results):
            self.assertEqual(first.name, second.name)
            self.assertEqual(
                first.recovered_revenue_paise, second.recovered_revenue_paise
            )
            self.assertEqual(first.contacts_made, second.contacts_made)
            self.assertEqual(first.policy_violations, second.policy_violations)


class TestTheAuditorIsActuallyLive(CounterfactualCase):
    """A sweep of clean rows is worthless if the auditor cannot detect anything.

    Every "zero violations" claim in this repository depends on the invariant
    auditor being awake. So at least one deliberately loosened variant must come
    back dirty; otherwise the clean rows prove nothing.
    """

    def test_loosening_the_contact_ceiling_is_caught(self):
        loosened = self.by_name["three_contacts"]
        self.assertGreater(
            loosened.policy_violations,
            0,
            "a variant permitting three contacts was audited against a "
            "two-contact governed ceiling and reported no violations, so the "
            "invariant auditor is not detecting ceiling breaches",
        )
        self.assertIn("REJECT", loosened.verdict)

    def test_variants_are_audited_against_governed_rules(self):
        """A loosened variant must not be scored against its own loosened bar."""
        loosened = next(
            v for v in default_variants() if v.name == "three_contacts"
        )
        # The variant itself permits three contacts...
        self.assertEqual(loosened.rules.max_customer_contacts, 3)
        # ...but the governed yardstick it is audited against permits two.
        self.assertEqual(GOVERNED_RULES.max_customer_contacts, 2)
        # ...and the run is therefore recorded as violating.
        self.assertGreater(self.by_name["three_contacts"].policy_violations, 0)


class TestConsentSurvivesPolicyLoosening(CounterfactualCase):
    """Consent must not be defeatable by flipping one policy flag.

    Opt-out is enforced independently in four places: `detection/rules.py`
    refuses to open a case, both strategists propose STOP, and the orchestrator
    terminates at INELIGIBLE before the policy engine is consulted. So disabling
    `stop_after_opt_out` is expected to change *nothing*.

    That null result is the assertion. If this test ever starts failing because
    the variant produced extra contacts, the redundant enforcement has collapsed
    into a single point of failure and consent now rests on one boolean.
    """

    def test_disabling_the_policy_rule_buys_no_extra_contact(self):
        consent = self.by_name["ignore_opt_out"]
        self.assertEqual(
            consent.contacts_delta,
            0,
            "disabling stop_after_opt_out bought extra customer contacts, so "
            "opt-out is no longer redundantly enforced upstream of policy",
        )
        self.assertEqual(consent.policy_violations, 0)
        self.assertIn("HELD", consent.verdict)

    def test_the_variant_is_marked_illegal_and_defence_in_depth(self):
        consent_variant = next(
            v for v in default_variants() if v.name == "ignore_opt_out"
        )
        self.assertFalse(consent_variant.rules.stop_after_opt_out)
        self.assertTrue(GOVERNED_RULES.stop_after_opt_out)
        self.assertFalse(consent_variant.legal)
        self.assertTrue(consent_variant.defence_in_depth)

    def test_an_alarm_is_raised_if_defence_in_depth_regresses(self):
        """The HELD verdict must not be unconditional."""
        from app.evaluation.counterfactual import VariantResult, _verdict

        baseline = VariantResult(
            name="governed_default",
            question="",
            legal=True,
            note="",
            is_baseline=True,
            recovered_revenue_paise=1000,
            contacts_made=100,
        )
        regressed = VariantResult(
            name="ignore_opt_out",
            question="",
            legal=False,
            note="",
            is_baseline=False,
            defence_in_depth=True,
            policy_violations=7,
        )
        regressed.contacts_delta = 12
        self.assertIn("ALARM", _verdict(regressed, baseline))


class TestMarginalEconomics(CounterfactualCase):
    def test_marginal_revenue_is_only_defined_when_contacts_increased(self):
        for result in self.result.results:
            if result.contacts_delta > 0:
                self.assertIsNotNone(result.marginal_revenue_per_contact_paise)
            else:
                self.assertIsNone(result.marginal_revenue_per_contact_paise)

    def test_baseline_deltas_are_zero(self):
        baseline = self.by_name["governed_default"]
        self.assertEqual(baseline.revenue_delta_paise, 0)
        self.assertEqual(baseline.contacts_delta, 0)

    def test_every_non_baseline_row_carries_a_verdict(self):
        for result in self.result.results:
            self.assertTrue(result.verdict, f"{result.name} has no verdict")

    def test_serialisation_round_trips_the_headline_fields(self):
        payload = self.result.to_dict()
        self.assertEqual(payload["baseline"], "governed_default")
        self.assertEqual(payload["dataset"]["seed"], SEED)
        self.assertEqual(payload["dataset"]["provenance"], "SYNTHETIC")
        self.assertIn("GOVERNED_RULES", payload["experimental_design"]["audited_against"])
        for row in payload["variants"]:
            self.assertIn("recovered_revenue_rupees", row)
            self.assertIn("verdict", row)


class TestCustomVariants(unittest.TestCase):
    def test_a_tighter_policy_can_be_priced_too(self):
        """The sandbox must work in the restrictive direction as well.

        Tightening is the direction a compliance team actually asks about, and a
        single-contact policy must not be able to out-recover a two-contact one.
        """
        dataset = generate(n_events=EVENTS, seed=SEED, profile="benchmark")
        variants = (
            PolicyVariant(
                name="governed_default",
                question="shipped",
                rules=GOVERNED_RULES,
                is_baseline=True,
            ),
            PolicyVariant(
                name="one_contact_only",
                question="What would a stricter single-contact policy cost?",
                rules=PolicyRules(max_customer_contacts=1),
            ),
        )
        result = sweep(dataset, variants=variants)
        strict = next(r for r in result.results if r.name == "one_contact_only")
        baseline = next(r for r in result.results if r.is_baseline)

        self.assertLessEqual(strict.contacts_made, baseline.contacts_made)
        self.assertEqual(strict.policy_violations, 0)
        self.assertLessEqual(strict.revenue_delta_paise, 0)


if __name__ == "__main__":
    unittest.main()

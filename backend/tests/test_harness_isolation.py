"""The benchmark harness must be a pure function of (dataset, strategy, seed).

Why this file exists
--------------------
``Customer.contacts_this_window`` is a mutable counter and the contact ceiling
is enforced by reading it. Running an arm therefore *wrote* to the caller's
``Customer`` objects.

``compare()`` hands the same ``Dataset`` to every arm in sequence. So every arm
after the first began with a customer book already carrying the previous arm's
contact counts, and was refused contacts it should have been allowed. The first
entry in ``STRATEGIES`` got a clean slate and the rest did not. Two consequences,
both bad:

1. The published comparison measured an arm's *position in the tuple* as well as
   its strategy. Reordering ``STRATEGIES`` would have changed the headline
   result.
2. Re-running one arm in a process that had already run something produced
   different numbers than running it alone, so a figure could not be reproduced
   by rerunning just that arm.

This is exactly the class of bug the repository's own thesis is about: a
measurement that quietly depends on hidden state. The harness now deep-copies
the customer book per run, and these tests hold that line.
"""

from __future__ import annotations

import unittest

from app.evaluation.generator import generate
from app.evaluation.harness import STRATEGIES, run_strategy

EVENTS = 300
SEED = 42


def _dataset():
    return generate(n_events=EVENTS, seed=SEED, profile="benchmark")


class TestRunStrategyDoesNotMutateTheDataset(unittest.TestCase):
    def test_customer_contact_counters_are_untouched(self):
        dataset = _dataset()
        before = {c.id: c.contacts_this_window for c in dataset.customers.values()}

        run_strategy(dataset, strategy="learning", seed="bench")

        after = {c.id: c.contacts_this_window for c in dataset.customers.values()}
        drifted = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        self.assertEqual(
            drifted,
            {},
            "run_strategy mutated the caller's customer contact counters, so "
            "any later arm run on this dataset starts contaminated",
        )

    def test_opt_out_flags_are_untouched(self):
        dataset = _dataset()
        before = {c.id: c.opted_out for c in dataset.customers.values()}
        run_strategy(dataset, strategy="learning", seed="bench")
        after = {c.id: c.opted_out for c in dataset.customers.values()}
        self.assertEqual(before, after)


class TestRepeatedRunsAreIdentical(unittest.TestCase):
    def test_the_same_arm_reruns_identically_on_a_reused_dataset(self):
        """The regression that started this investigation.

        Before the fix this produced three different revenue figures from three
        identical calls.
        """
        dataset = _dataset()
        runs = [
            run_strategy(dataset, strategy="learning", seed="bench")[0]
            for _ in range(3)
        ]
        revenues = [m.recovered_revenue for m in runs]
        contacts = [m.contacts_made for m in runs]

        self.assertEqual(
            len(set(revenues)),
            1,
            f"identical calls returned different revenue: {revenues}",
        )
        self.assertEqual(
            len(set(contacts)),
            1,
            f"identical calls returned different contact counts: {contacts}",
        )

    def test_a_reused_dataset_matches_a_fresh_one(self):
        """Reusing a dataset must equal generating an identical fresh one."""
        shared = _dataset()
        run_strategy(shared, strategy="learning", seed="bench")
        reused, _, _ = run_strategy(shared, strategy="learning", seed="bench")
        fresh, _, _ = run_strategy(_dataset(), strategy="learning", seed="bench")

        self.assertEqual(reused.recovered_revenue, fresh.recovered_revenue)
        self.assertEqual(reused.contacts_made, fresh.contacts_made)


class TestArmsDoNotContaminateEachOther(unittest.TestCase):
    def test_arm_result_is_independent_of_what_ran_before_it(self):
        """An arm's numbers must not depend on its position in the sweep.

        This is the property that makes the published comparison a comparison of
        strategies rather than of tuple ordering.
        """
        alone, _, _ = run_strategy(_dataset(), strategy="learning", seed="bench")

        shared = _dataset()
        for other in ("ungoverned", "fixed_baseline", "oracle"):
            run_strategy(shared, strategy=other, seed="bench")
        after_others, _, _ = run_strategy(shared, strategy="learning", seed="bench")

        self.assertEqual(
            after_others.recovered_revenue,
            alone.recovered_revenue,
            "the learning arm's revenue changed depending on which arms ran "
            "before it on the same dataset",
        )
        self.assertEqual(after_others.contacts_made, alone.contacts_made)

    def test_the_ungoverned_arm_cannot_starve_a_later_arm_of_contacts(self):
        """The worst case of the bug, isolated.

        The ungoverned arm makes roughly seven times as many contacts as any
        governed arm. When it ran first on a shared dataset it exhausted the
        contact counters, so a governed arm running afterwards was denied
        contacts by a ceiling it had not spent.
        """
        shared = _dataset()
        run_strategy(shared, strategy="ungoverned", seed="bench")
        after_ungoverned, _, _ = run_strategy(shared, strategy="learning", seed="bench")

        clean, _, _ = run_strategy(_dataset(), strategy="learning", seed="bench")

        self.assertEqual(after_ungoverned.contacts_made, clean.contacts_made)
        self.assertEqual(after_ungoverned.recovered_revenue, clean.recovered_revenue)

    def test_every_declared_strategy_is_order_independent(self):
        """Cheap smoke check across all arms on a small dataset."""
        small = 120
        for strategy in STRATEGIES:
            alone, _, _ = run_strategy(
                generate(n_events=small, seed=SEED, profile="benchmark"),
                strategy=strategy,
                seed="bench",
            )
            shared = generate(n_events=small, seed=SEED, profile="benchmark")
            run_strategy(shared, strategy="ungoverned", seed="bench")
            after, _, _ = run_strategy(shared, strategy=strategy, seed="bench")
            self.assertEqual(
                after.recovered_revenue,
                alone.recovered_revenue,
                f"arm {strategy!r} is sensitive to what ran before it",
            )


if __name__ == "__main__":
    unittest.main()

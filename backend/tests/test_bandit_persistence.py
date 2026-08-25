"""Tests for ContextualBandit save/load persistence."""

from __future__ import annotations

import os
import tempfile
import unittest

from app.agents.bandit import ContextualBandit, DEFAULT_ARMS, Posterior
from app.agents.features import CaseFeatures


class TestBanditPersistence(unittest.TestCase):
    def _tmp_db(self) -> str:
        """Return a temp path that does not yet exist."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(path)  # Remove so bandit can create fresh
        self._paths_to_clean.append(path)
        return path

    def setUp(self) -> None:
        self._paths_to_clean: list[str] = []

    def tearDown(self) -> None:
        for p in self._paths_to_clean:
            if os.path.exists(p):
                os.unlink(p)

    # ------------------------------------------------------------------ #
    # 1. Save and load an empty bandit (no observations made)
    # ------------------------------------------------------------------ #

    def test_save_and_load_empty_bandit(self) -> None:
        path = self._tmp_db()
        b = ContextualBandit(seed="test-empty")
        b.save(path)

        loaded = ContextualBandit.load(path, seed="test-empty")

        self.assertEqual(loaded.seed, "test-empty")
        self.assertEqual(loaded.decisions, 0)
        self.assertEqual(loaded.explorations, 0)
        # Empty bandit has no posteriors saved yet (warm-start cells are lazy)
        self.assertEqual(len(loaded.posteriors), 0)

    # ------------------------------------------------------------------ #
    # 2. Save after updates; verify posteriors survive the round-trip
    # ------------------------------------------------------------------ #

    def test_save_and_load_after_updates(self) -> None:
        path = self._tmp_db()
        b = ContextualBandit(seed="test-updates")

        arm = DEFAULT_ARMS[0]
        segment = "high_value_card_expired"

        for i in range(10):
            b.update(segment, arm, recovered=(i % 2 == 0))  # 5 wins, 5 losses

        b.decisions = 12
        b.explorations = 3
        b.save(path)

        loaded = ContextualBandit.load(path, seed="test-updates")

        self.assertEqual(loaded.decisions, 12)
        self.assertEqual(loaded.explorations, 3)

        key = (segment, arm.id)
        self.assertIn(key, loaded.posteriors)
        p = loaded.posteriors[key]
        self.assertEqual(p.pulls, 10)
        self.assertEqual(p.wins, 5)
        # alpha / beta should match (started at 0 since no _posterior warm-start)
        self.assertAlmostEqual(p.alpha, b.posteriors[key].alpha, places=6)
        self.assertAlmostEqual(p.beta, b.posteriors[key].beta, places=6)

    # ------------------------------------------------------------------ #
    # 3. Loading from a missing path returns a fresh bandit
    # ------------------------------------------------------------------ #

    def test_load_nonexistent_path(self) -> None:
        path = "/tmp/does_not_exist_bandit_xyz_12345.db"
        if os.path.exists(path):
            os.unlink(path)  # Ensure truly missing

        loaded = ContextualBandit.load(path, seed="fresh-seed")

        self.assertEqual(loaded.decisions, 0)
        self.assertEqual(loaded.explorations, 0)
        self.assertEqual(len(loaded.posteriors), 0)

    # ------------------------------------------------------------------ #
    # 4. Learning continues to accumulate after loading persisted state
    # ------------------------------------------------------------------ #

    def test_learning_continues_after_load(self) -> None:
        path = self._tmp_db()
        arm = DEFAULT_ARMS[1]  # PAYMENT_LINK+5
        segment = "mid_value_upi_failure"

        # Phase 1: 5 updates, save
        b1 = ContextualBandit(seed="continuity")
        for i in range(5):
            b1.update(segment, arm, recovered=True)
        b1.save(path)

        # Phase 2: load then make 5 more updates
        b2 = ContextualBandit.load(path, seed="continuity")
        for i in range(5):
            b2.update(segment, arm, recovered=False)

        key = (segment, arm.id)
        p = b2.posteriors[key]
        # Total pulls should be 10 (5 from first session + 5 from second)
        self.assertEqual(p.pulls, 10)
        self.assertEqual(p.wins, 5)

        # Save again and reload to verify the second batch persisted
        b2.save(path)
        b3 = ContextualBandit.load(path, seed="continuity")
        p3 = b3.posteriors[key]
        self.assertEqual(p3.pulls, 10)
        self.assertEqual(p3.wins, 5)


if __name__ == "__main__":
    unittest.main()

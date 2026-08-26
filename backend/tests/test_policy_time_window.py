"""Tests for time-of-day contact window policy rule."""
from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.domain.entities import InterventionType
from app.policies.config import PolicyRules, PolicyVersion
from app.policies.engine import PolicyEngine
from tests.factories import case, customer, plan


def _engine_with_window(before: int = 8, after: int = 21) -> PolicyEngine:
    rules = PolicyRules(no_contact_before_hour=before, no_contact_after_hour=after)
    return PolicyEngine(PolicyVersion(id="test_tw", rules=rules))


class TestPolicyTimeWindow(unittest.TestCase):

    def test_contact_allowed_during_window(self):
        """At 10 AM UTC the policy should not fire the time window rule."""
        engine = _engine_with_window()
        c = case()
        cust = customer()
        p = plan()
        with patch("app.policies.engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 15, 10, 0, tzinfo=UTC)
            decision = engine.authorize(c, p, cust)
        self.assertNotIn("contact_time_window", decision.rule_ids)

    def test_contact_denied_before_window(self):
        """At 3 AM UTC, no customer contact is allowed."""
        engine = _engine_with_window()
        c = case()
        cust = customer()
        p = plan()
        with patch("app.policies.engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 15, 3, 0, tzinfo=UTC)
            decision = engine.authorize(c, p, cust)
        self.assertFalse(decision.allowed)
        self.assertIn("contact_time_window", decision.rule_ids)
        self.assertTrue(any("contact outside allowed hours" in r for r in decision.reasons))

    def test_contact_denied_after_window(self):
        """At 22:00 UTC no customer contact is allowed."""
        engine = _engine_with_window()
        c = case()
        cust = customer()
        p = plan()
        with patch("app.policies.engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 15, 22, 0, tzinfo=UTC)
            decision = engine.authorize(c, p, cust)
        self.assertFalse(decision.allowed)
        self.assertIn("contact_time_window", decision.rule_ids)

    def test_stop_bypasses_time_window(self):
        """STOP is unconditionally permitted regardless of time."""
        engine = _engine_with_window()
        c = case()
        cust = customer()
        p = plan(intervention=InterventionType.STOP, contact=False)
        with patch("app.policies.engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 15, 3, 0, tzinfo=UTC)
            decision = engine.authorize(c, p, cust)
        self.assertTrue(decision.allowed)
        self.assertIn("stop_always_allowed", decision.rule_ids)


if __name__ == "__main__":
    unittest.main()

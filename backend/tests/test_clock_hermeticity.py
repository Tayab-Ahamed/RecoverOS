"""Machine-enforced guard: no test verdict may depend on the wall clock.

Why this file exists
--------------------
The policy engine's ``contact_time_window`` rule reads the current hour. The
engine docstring already warns that a wall-clock engine "makes the verdict
depend on when the suite happens to run", and the benchmark harness pins
``EVAL_CLOCK_NOW`` for exactly that reason.

The test suite did not. Seventeen tests across ``test_orchestrator``,
``test_policy_engine`` and ``test_razorpay_policy`` constructed a bare
``PolicyEngine()``, so between 21:00 and 08:00 UTC every contact-bearing action
was denied and those tests failed -- including the orchestrator happy path,
which has nothing to do with time-of-day policy. 08:00 UTC is 13:30 IST, so the
failing window covered most of an Indian working morning while the README
advertised a green suite.

Nothing was logically wrong with the engine, the rule, or the tests' intent.
The seam existed and was simply not used. So the invariant is now enforced by a
test rather than by remembering:

1. every ``PolicyEngine(...)`` built under ``tests/`` injects a clock, and
2. the engine is provably time-independent apart from the one rule that is
   supposed to read the hour.

The AST scan needs no installed packages, in the same spirit as
``scripts/static_check.py``: a safety claim that can only be checked when the
network is up is not a safety claim.
"""

from __future__ import annotations

import ast
import pathlib
import unittest
from datetime import UTC, datetime

from app.domain.entities import InterventionType
from app.policies.config import PolicyRules, PolicyVersion
from app.policies.engine import PolicyEngine
from tests import factories as f

TESTS_DIR = pathlib.Path(__file__).resolve().parent

# Modules whose entire purpose is to exercise the time-of-day rule. They inject
# hours deliberately via mock.patch rather than passing a clock, so a bare
# construction there is correct rather than a latent wall-clock dependency.
CLOCK_OWNING_MODULES = {"test_policy_time_window.py"}


class TestNoBarePolicyEngineInTests(unittest.TestCase):
    """Every engine built in a test must be given an explicit clock."""

    def test_every_policy_engine_construction_injects_a_clock(self):
        offenders: list[str] = []

        for path in sorted(TESTS_DIR.glob("test_*.py")):
            if path.name in CLOCK_OWNING_MODULES or path.name == pathlib.Path(__file__).name:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else func.attr
                    if isinstance(func, ast.Attribute)
                    else None
                )
                if name != "PolicyEngine":
                    continue
                if not any(kw.arg == "clock" for kw in node.keywords):
                    offenders.append(f"{path.name}:{node.lineno}")

        self.assertEqual(
            offenders,
            [],
            "PolicyEngine built without clock= in tests, so these verdicts depend "
            "on the hour the suite runs and will fail outside "
            f"{PolicyRules().no_contact_before_hour:02d}:00-"
            f"{PolicyRules().no_contact_after_hour:02d}:00 UTC: "
            + ", ".join(offenders)
            + ". Pass clock=f.fixed_clock (see tests/factories.py).",
        )

    def test_every_testclient_module_sets_clock(self):
        """Any test file constructing TestClient must call set_clock in its setup."""
        offenders: list[str] = []

        for path in sorted(TESTS_DIR.glob("test_*.py")):
            text = path.read_text()
            if "TestClient" not in text:
                continue
            tree = ast.parse(text, filename=str(path))
            has_test_client = False
            has_set_clock = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = (
                        func.id
                        if isinstance(func, ast.Name)
                        else func.attr
                        if isinstance(func, ast.Attribute)
                        else None
                    )
                    if name == "TestClient":
                        has_test_client = True
                    elif name == "set_clock":
                        has_set_clock = True

            if has_test_client and not has_set_clock:
                offenders.append(path.name)

        self.assertEqual(
            offenders,
            [],
            "Test module uses TestClient without calling set_clock(): "
            + ", ".join(offenders)
            + ". Without set_clock(fixed_clock), the global API container will read "
            "the live wall clock and fail outside contact hours.",
        )

    def test_the_wired_test_system_pins_its_clock(self):
        """factories.System must not hand out a wall-clock engine."""
        system = f.System()
        self.assertEqual(system.policy._clock(), f.fixed_clock())


class TestEngineIsTimeIndependentApartFromTheWindowRule(unittest.TestCase):
    """Only ``contact_time_window`` may change its mind as the hour moves."""

    def _authorize_at(self, hour: int):
        engine = PolicyEngine(
            PolicyVersion(id="hermeticity", rules=PolicyRules()),
            clock=lambda: datetime(2026, 8, 20, hour, 0, tzinfo=UTC),
        )
        return engine.authorize(f.case(), f.plan(), f.customer())

    def test_only_the_window_rule_varies_across_all_twenty_four_hours(self):
        rules = PolicyRules()
        for hour in range(24):
            decision = self._authorize_at(hour)
            other_rules = {r for r in decision.rule_ids if r != "contact_time_window"}
            self.assertEqual(
                other_rules,
                set(),
                f"at {hour:02d}:00 UTC a rule other than the time window fired: "
                f"{sorted(other_rules)}. A clean case must only ever be refused "
                "for being out of hours.",
            )

            in_window = rules.no_contact_before_hour <= hour < rules.no_contact_after_hour
            self.assertEqual(
                decision.allowed,
                in_window,
                f"clean case at {hour:02d}:00 UTC: allowed={decision.allowed}, "
                f"expected {in_window}",
            )

    def test_stop_is_permitted_at_every_hour(self):
        """The system must never be unable to stop, including at 03:00."""
        for hour in range(24):
            engine = PolicyEngine(
                clock=lambda h=hour: datetime(2026, 8, 20, h, 0, tzinfo=UTC)
            )
            decision = engine.authorize(
                f.case(),
                f.plan(InterventionType.STOP, contact=False),
                f.customer(),
            )
            self.assertTrue(decision.allowed, f"STOP was refused at {hour:02d}:00 UTC")


if __name__ == "__main__":
    unittest.main()

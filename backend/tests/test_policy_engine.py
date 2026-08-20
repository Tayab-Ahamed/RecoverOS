import unittest

from app.domain.entities import InterventionType
from app.domain.money import Money
from app.policies.config import PolicyRules, PolicyVersion
from app.policies.engine import PolicyEngine
from tests import factories as f


class TestPolicyEngine(unittest.TestCase):
    def setUp(self):
        self.engine = PolicyEngine()

    def test_clean_case_is_allowed(self):
        d = self.engine.authorize(f.case(), f.plan(), f.customer())
        self.assertTrue(d.allowed)
        self.assertFalse(d.requires_human_approval)

    def test_opted_out_customer_is_denied(self):
        d = self.engine.authorize(f.case(), f.plan(), f.customer(opted_out=True))
        self.assertFalse(d.allowed)
        self.assertIn("stop_after_opt_out", d.rule_ids)

    def test_attempt_ceiling(self):
        d = self.engine.authorize(f.case(attempts=3), f.plan(), f.customer())
        self.assertFalse(d.allowed)
        self.assertIn("max_recovery_attempts", d.rule_ids)

    def test_contact_ceiling(self):
        d = self.engine.authorize(f.case(contacts_made=2), f.plan(), f.customer())
        self.assertFalse(d.allowed)
        self.assertIn("max_customer_contacts", d.rule_ids)

    def test_economic_floor_is_one_hundred_rupees(self):
        # Contradiction C9 resolved: Rs 100 is 10000 paise.
        self.assertEqual(self.engine.rules.min_recovery_value, Money(10000))
        below = self.engine.authorize(f.case(f.event(rupees=99)), f.plan(), f.customer())
        self.assertFalse(below.allowed)
        self.assertIn("min_recovery_value", below.rule_ids)
        at = self.engine.authorize(f.case(f.event(rupees=100)), f.plan(), f.customer())
        self.assertTrue(at.allowed)

    def test_discount_cap(self):
        self.assertTrue(
            self.engine.authorize(f.case(), f.plan(discount=10.0), f.customer()).allowed
        )
        bad = self.engine.authorize(f.case(), f.plan(discount=10.1), f.customer())
        self.assertFalse(bad.allowed)
        self.assertIn("max_discount_percentage", bad.rule_ids)

    def test_high_value_escalates_rather_than_denying(self):
        d = self.engine.authorize(f.case(f.event(rupees=50000)), f.plan(), f.customer())
        self.assertTrue(d.allowed)
        self.assertTrue(d.requires_human_approval)

    def test_already_recovered_case_cannot_be_actioned_again(self):
        c = f.case()
        c.evidence = f.evidence()
        d = self.engine.authorize(c, f.plan(), f.customer())
        self.assertFalse(d.allowed)
        self.assertIn("stop_after_success", d.rule_ids)

    def test_stop_is_always_permitted(self):
        # The system must never be unable to stop, whatever else is true.
        c = f.case(f.event(rupees=1), attempts=99, contacts_made=99)
        d = self.engine.authorize(
            c, f.plan(InterventionType.STOP, contact=False), f.customer(opted_out=True)
        )
        self.assertTrue(d.allowed)

    def test_decision_carries_policy_version_and_id(self):
        engine = PolicyEngine(PolicyVersion(id="v12", rules=PolicyRules()))
        d = engine.authorize(f.case(), f.plan(), f.customer())
        self.assertEqual(d.policy_version_id, "v12")
        self.assertTrue(d.id.startswith("dec_"))

    def test_policy_version_is_content_addressed(self):
        a = PolicyVersion(id="a", rules=PolicyRules())
        b = PolicyVersion(id="b", rules=PolicyRules())
        c = PolicyVersion(id="c", rules=PolicyRules(max_recovery_attempts=5))
        self.assertEqual(a.checksum, b.checksum)
        self.assertNotEqual(a.checksum, c.checksum)

    def test_denials_are_explained(self):
        d = self.engine.authorize(f.case(attempts=5), f.plan(), f.customer(opted_out=True))
        self.assertFalse(d.allowed)
        self.assertGreaterEqual(len(d.reasons), 2)
        self.assertIn("DENY", d.summary)

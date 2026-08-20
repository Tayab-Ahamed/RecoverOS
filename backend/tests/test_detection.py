import unittest

from app.detection.rules import detect, priority_score, recovery_probability
from app.domain.entities import FailureReason
from app.domain.money import Money
from tests import factories as f


class TestDetection(unittest.TestCase):
    def test_opted_out_customer_has_zero_probability(self):
        self.assertEqual(
            recovery_probability(f.event(), f.customer(opted_out=True)), 0.0
        )

    def test_probability_varies_by_cause(self):
        technical = recovery_probability(
            f.event(reason=FailureReason.TECHNICAL_ERROR), f.customer()
        )
        abandoned = recovery_probability(
            f.event(reason=FailureReason.ABANDONED_CHECKOUT), f.customer()
        )
        self.assertGreater(technical, abandoned)

    def test_repeated_contact_depresses_probability(self):
        fresh = recovery_probability(f.event(), f.customer(contacts_this_window=0))
        tired = recovery_probability(f.event(), f.customer(contacts_this_window=2))
        self.assertLess(tired, fresh)

    def test_probability_is_bounded(self):
        for reason in FailureReason:
            p = recovery_probability(f.event(reason=reason), f.customer())
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 0.95)

    def test_high_value_customer_gets_higher_priority(self):
        small = priority_score(
            f.event(), f.customer(lifetime_value=Money.from_rupees(1000)), f.NOW
        )
        large = priority_score(
            f.event(), f.customer(lifetime_value=Money.from_rupees(200000)), f.NOW
        )
        self.assertGreater(large, small)

    def test_detection_is_deterministic_and_ordered(self):
        events = [
            f.event(id="evt_a", rupees=100),
            f.event(id="evt_b", rupees=90000),
            f.event(id="evt_c", rupees=5000),
        ]
        customers = {"cust_1": f.customer()}
        first = detect(events, customers, f.NOW)
        second = detect(events, customers, f.NOW)
        self.assertEqual([s.event.id for s in first], [s.event.id for s in second])
        self.assertEqual(first[0].event.id, "evt_b")

    def test_events_without_a_known_customer_are_skipped(self):
        self.assertEqual(detect([f.event()], {}, f.NOW), [])

    def test_expected_recoverable_value(self):
        signal = detect([f.event(rupees=10000)], {"cust_1": f.customer()}, f.NOW)[0]
        expected = signal.revenue_at_risk.scaled(signal.recovery_probability)
        self.assertEqual(signal.expected_recoverable_value, expected)

    def test_provenance_mixing_is_refused(self):
        from app.detection.rules import assert_single_provenance
        from app.domain.entities import DataProvenance

        live = f.customer(provenance=DataProvenance.LIVE_TEST_MODE)
        synthetic = f.customer(provenance=DataProvenance.SYNTHETIC)
        with self.assertRaises(ValueError):
            assert_single_provenance([live, synthetic])

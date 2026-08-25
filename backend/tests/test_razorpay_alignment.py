"""Tests for the Razorpay-alignment layer.

These assert facts taken from Razorpay's own documentation, so if Razorpay
changes behaviour these tests are where it should surface.
"""

from __future__ import annotations

import unittest

from app.domain.entities import FailureReason, InterventionType
from app.integrations import razorpay_catalog as cat
from app.integrations.razorpay_errors import DeclineClass, classify, classify_payment_entity
from app.integrations.razorpay_gateway_window import (
    GATEWAY_RETRY_OFFSETS_DAYS,
    assess_window,
    check_pre_debit_notification,
)


class TestDeclineClassification(unittest.TestCase):
    def test_expired_card_is_hard_and_blocks_same_instrument_retry(self):
        v = classify(error_code="BAD_REQUEST_ERROR", error_reason="card_expired")
        self.assertIs(v.reason, FailureReason.CARD_EXPIRED)
        self.assertIs(v.decline_class, DeclineClass.HARD)
        self.assertFalse(v.same_instrument_retry_ok)
        self.assertTrue(v.requires_customer_action)

    def test_insufficient_funds_is_soft_and_retryable(self):
        v = classify(error_reason="insufficient_funds", error_source="customer")
        self.assertIs(v.reason, FailureReason.INSUFFICIENT_FUNDS)
        self.assertIs(v.decline_class, DeclineClass.SOFT)
        self.assertTrue(v.same_instrument_retry_ok)

    def test_gateway_error_is_transient_and_needs_no_customer_contact(self):
        v = classify(error_code="GATEWAY_ERROR", error_source="gateway")
        self.assertIs(v.decline_class, DeclineClass.TRANSIENT)
        self.assertTrue(v.same_instrument_retry_ok)
        self.assertFalse(v.requires_customer_action)

    def test_business_source_never_contacts_the_customer(self):
        # Our own bad request must not turn into a dunning message.
        v = classify(error_code="BAD_REQUEST_ERROR", error_source="business")
        self.assertFalse(v.requires_customer_action)
        self.assertFalse(v.same_instrument_retry_ok)

    def test_unknown_fields_do_not_default_to_retryable(self):
        # Regression guard: an optimistic default would manufacture retries
        # that the evidence does not support.
        v = classify(error_reason="something_we_have_never_seen")
        self.assertIs(v.decline_class, DeclineClass.UNKNOWN)
        self.assertFalse(v.same_instrument_retry_ok)

    def test_classify_real_webhook_payment_entity(self):
        # Shape copied from Razorpay's Payments API reference sample.
        payment = {
            "error_code": "BAD_REQUEST_ERROR",
            "error_description": "Payment processing failed because of incorrect OTP",
            "error_source": "customer",
            "error_step": "payment_authentication",
            "error_reason": "incorrect_otp",
        }
        v = classify_payment_entity(payment)
        self.assertIs(v.reason, FailureReason.AUTHENTICATION_FAILED)
        self.assertTrue(v.same_instrument_retry_ok)


class TestProductCatalog(unittest.TestCase):
    def test_every_intervention_is_mapped(self):
        for intervention in InterventionType:
            self.assertIn(intervention, cat.CATALOG)

    def test_stop_and_escalation_make_no_provider_call(self):
        for intervention in (InterventionType.STOP, InterventionType.ESCALATION):
            self.assertFalse(cat.spec_for(intervention).is_provider_call)
            self.assertFalse(cat.spec_for(intervention).contacts_customer)

    def test_subscription_recovery_requires_a_mandate(self):
        self.assertTrue(
            cat.spec_for(InterventionType.SUBSCRIPTION_RECOVERY).requires_existing_mandate
        )
        available = cat.available_interventions(has_mandate=False)
        self.assertNotIn(InterventionType.SUBSCRIPTION_RECOVERY, available)
        self.assertIn(InterventionType.PAYMENT_LINK, available)

    def test_cross_product_evidence_is_rejected(self):
        # A paid payment link does not prove a mandate debit succeeded.
        self.assertFalse(
            cat.proves_recovery(
                InterventionType.SUBSCRIPTION_RECOVERY, "payment_link.paid"
            )
        )
        self.assertTrue(
            cat.proves_recovery(
                InterventionType.SUBSCRIPTION_RECOVERY, "subscription.charged"
            )
        )
        self.assertTrue(
            cat.proves_recovery(InterventionType.PAYMENT_LINK, "payment_link.paid")
        )

    def test_no_event_is_both_proof_and_failure(self):
        overlap = cat.all_confirming_events() & cat.all_failing_events()
        self.assertEqual(overlap, frozenset())

    def test_mandate_products_flag_rbi_notification(self):
        self.assertTrue(
            cat.spec_for(
                InterventionType.SUBSCRIPTION_RECOVERY
            ).rbi_pre_debit_notification_required
        )


class TestGatewayRetryWindow(unittest.TestCase):
    def test_razorpay_ladder_is_t_plus_1_to_3(self):
        self.assertEqual(GATEWAY_RETRY_OFFSETS_DAYS, (1, 2, 3))

    def test_gateway_owns_recovery_immediately_after_mandate_failure(self):
        v = assess_window("pending", days_since_failure=0.2)
        self.assertTrue(v.gateway_owns_recovery)
        self.assertFalse(v.contact_allowed)
        self.assertEqual(v.retries_remaining, 3)

    def test_retries_remaining_decreases_across_the_ladder(self):
        self.assertEqual(assess_window("pending", 1.5).retries_remaining, 2)
        self.assertEqual(assess_window("pending", 2.5).retries_remaining, 1)

    def test_agent_takes_over_after_ladder_is_exhausted(self):
        v = assess_window("pending", days_since_failure=4.0)
        self.assertFalse(v.gateway_owns_recovery)
        self.assertTrue(v.contact_allowed)

    def test_halted_hands_control_to_the_agent(self):
        v = assess_window("halted", days_since_failure=3.0)
        self.assertFalse(v.gateway_owns_recovery)
        self.assertTrue(v.contact_allowed)

    def test_one_off_payment_failure_has_no_gateway_ladder(self):
        v = assess_window(None, days_since_failure=0.0)
        self.assertFalse(v.gateway_owns_recovery)
        self.assertTrue(v.contact_allowed)


class TestPreDebitNotification(unittest.TestCase):
    def test_missing_notification_is_a_violation_not_an_unknown(self):
        self.assertFalse(check_pre_debit_notification(None).compliant)

    def test_less_than_24h_notice_is_non_compliant(self):
        self.assertFalse(check_pre_debit_notification(6.0).compliant)

    def test_24h_notice_is_compliant(self):
        self.assertTrue(check_pre_debit_notification(24.0).compliant)
        self.assertTrue(check_pre_debit_notification(48.0).compliant)


if __name__ == "__main__":
    unittest.main()

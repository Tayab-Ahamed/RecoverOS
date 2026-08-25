"""Which real Razorpay product each internal intervention actually uses.

Up to now `InterventionType` was an abstract label. To deploy on a live
Razorpay account, each label must name a concrete product, a concrete API
endpoint, and the webhook events that constitute proof of success. This module
is that mapping, and it is deliberately data rather than scattered branches so
tests can assert over the whole catalogue.

Two properties matter more than the mapping itself:

1. `confirming_events` is what the Outcome Verifier is allowed to accept as
   proof for that product. A subscription charge is proven by
   `subscription.charged`, not by `payment_link.paid`. Accepting the wrong
   event is how a system reports recoveries that did not happen.

2. `requires_existing_mandate` encodes a hard eligibility fact: subscription
   recovery is only available if the customer already authorised a mandate.
   Proposing it otherwise is not a policy preference, it is impossible, and
   the strategist must not be able to select it.

Sources: Razorpay Payment Links API, Subscriptions API and Payment Retries,
Subscriptions and Payments webhook event catalogues, UPI AutoPay product page.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.entities import InterventionType

API_BASE = "https://api.razorpay.com/v1"


@dataclass(frozen=True)
class RazorpayProductSpec:
    intervention: InterventionType
    product: str
    endpoint: str | None
    method: str | None
    contacts_customer: bool
    requires_existing_mandate: bool
    confirming_events: frozenset[str]
    failing_events: frozenset[str]
    docs: str
    notes: str = ""
    rbi_pre_debit_notification_required: bool = False

    @property
    def is_provider_call(self) -> bool:
        return self.endpoint is not None


CATALOG: dict[InterventionType, RazorpayProductSpec] = {
    InterventionType.PAYMENT_LINK: RazorpayProductSpec(
        intervention=InterventionType.PAYMENT_LINK,
        product="Razorpay Payment Links (Standard)",
        endpoint="/payment_links",
        method="POST",
        contacts_customer=True,
        requires_existing_mandate=False,
        confirming_events=frozenset({"payment_link.paid", "payment.captured", "order.paid"}),
        failing_events=frozenset(
            {"payment_link.expired", "payment_link.cancelled", "payment.failed"}
        ),
        docs="https://razorpay.com/docs/api/payments/payment-links/",
        notes=(
            "Amount in paise. reference_id carries our case id and is unique per "
            "link, which is what makes creation idempotent. Links are valid six "
            "months by default; we set expire_by far shorter so an unpaid link "
            "produces a terminal signal instead of hanging forever."
        ),
    ),
    InterventionType.SUBSCRIPTION_RECOVERY: RazorpayProductSpec(
        intervention=InterventionType.SUBSCRIPTION_RECOVERY,
        product="Razorpay Subscriptions / UPI AutoPay mandate charge",
        endpoint="/invoices/{invoice_id}/issue",
        method="POST",
        contacts_customer=True,
        requires_existing_mandate=True,
        confirming_events=frozenset({"subscription.charged", "payment.captured"}),
        failing_events=frozenset(
            {"subscription.pending", "subscription.halted", "payment.failed"}
        ),
        docs="https://razorpay.com/docs/payments/subscriptions/payment-retries/",
        rbi_pre_debit_notification_required=True,
        notes=(
            "Only available while the invoice is in the issued state. Razorpay "
            "does not support manual charging of a domestic card, so for card "
            "mandates this degrades to asking the customer to update the card. "
            "RBI e-mandate rules require a pre-debit notification at least 24 "
            "hours before any debit."
        ),
    ),
    InterventionType.REMINDER: RazorpayProductSpec(
        intervention=InterventionType.REMINDER,
        product="Razorpay Payment Link reminders",
        endpoint="/payment_links/{id}/notify_by/{medium}",
        method="POST",
        contacts_customer=True,
        requires_existing_mandate=False,
        confirming_events=frozenset({"payment_link.paid", "payment.captured"}),
        failing_events=frozenset({"payment_link.expired"}),
        docs="https://razorpay.com/docs/api/payments/payment-links/reminders/",
        notes=(
            "Cheapest real action available: it reuses an existing link rather "
            "than minting a new one, so it costs one contact and no new "
            "payment object. Razorpay also sends its own reminders when "
            "reminder_enable is true, which we must count as contact."
        ),
    ),
    InterventionType.ESCALATION: RazorpayProductSpec(
        intervention=InterventionType.ESCALATION,
        product="Internal human queue (no Razorpay call)",
        endpoint=None,
        method=None,
        contacts_customer=False,
        requires_existing_mandate=False,
        confirming_events=frozenset(),
        failing_events=frozenset(),
        docs="",
        notes=(
            "Not a Razorpay product. Measured as strictly dominated by the "
            "benchmark and therefore removed from the bandit arm set."
        ),
    ),
    InterventionType.STOP: RazorpayProductSpec(
        intervention=InterventionType.STOP,
        product="No action",
        endpoint=None,
        method=None,
        contacts_customer=False,
        requires_existing_mandate=False,
        confirming_events=frozenset(),
        failing_events=frozenset(),
        docs="",
        notes="Always available. The system must never be unable to stop.",
    ),
}


def spec_for(intervention: InterventionType) -> RazorpayProductSpec:
    try:
        return CATALOG[intervention]
    except KeyError as exc:
        raise KeyError(f"no Razorpay product mapped for {intervention}") from exc


def all_confirming_events() -> frozenset[str]:
    """Every event that can ever prove a recovery, across all products."""
    out: set[str] = set()
    for spec in CATALOG.values():
        out |= spec.confirming_events
    return frozenset(out)


def all_failing_events() -> frozenset[str]:
    out: set[str] = set()
    for spec in CATALOG.values():
        out |= spec.failing_events
    return frozenset(out)


def proves_recovery(intervention: InterventionType, event_type: str) -> bool:
    """Whether this event is valid proof for THIS product specifically.

    Cross-product proof is rejected: a payment link being paid says nothing
    about whether a mandate debit succeeded.
    """
    return event_type in spec_for(intervention).confirming_events


def available_interventions(has_mandate: bool) -> tuple[InterventionType, ...]:
    """Interventions that are physically possible for this customer."""
    return tuple(
        spec.intervention
        for spec in CATALOG.values()
        if has_mandate or not spec.requires_existing_mandate
    )

"""Razorpay's own recovery behaviour, which our agent must not duplicate.

This is the most important thing learned from reading Razorpay's docs, and it
is a correctness issue rather than a feature.

When a Subscriptions auto-charge fails, Razorpay does not sit still. Per their
Payment Retries documentation:

    T+0   charge attempted, fails -> subscription moves to `pending`
    T+1   Razorpay automatically reattempts
    T+2   Razorpay automatically reattempts
    T+3   Razorpay automatically reattempts
    after that, subscription moves to `halted`

So for three days after a mandate failure, the gateway is already retrying for
free, with no contact cost to us. An agent that dunned the customer on day one
would be spending a scarce contact to chase a payment that the provider was
about to retry anyway, and would take credit for the gateway's recovery.

This produces two rules:

1. While the gateway owns the retry window, the only useful actions are
   no-contact ones. Waiting is not passivity here, it is the correct move.
2. `subscription.halted` is the real trigger for agent-led recovery, because
   it is the point at which the provider has given up and stops charging.

It also encodes the RBI e-mandate constraint: a pre-debit notification must
reach the customer at least 24 hours before any mandate debit. A debit
proposed inside that window is not merely inadvisable, it is non-compliant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

# Razorpay Subscriptions auto-retry schedule, in days after the failed charge.
GATEWAY_RETRY_OFFSETS_DAYS: tuple[int, ...] = (1, 2, 3)
GATEWAY_RETRY_WINDOW = timedelta(days=max(GATEWAY_RETRY_OFFSETS_DAYS))

# RBI mandate rule for cards and UPI AutoPay.
PRE_DEBIT_NOTIFICATION_LEAD = timedelta(hours=24)

# Subscription states as Razorpay reports them.
SUBSCRIPTION_PENDING = "pending"
SUBSCRIPTION_HALTED = "halted"
SUBSCRIPTION_ACTIVE = "active"

# The event that means the provider has stopped trying and it is now our turn.
GATEWAY_GAVE_UP_EVENTS = frozenset({"subscription.halted"})
# Events that mean the provider is still working the case.
GATEWAY_STILL_TRYING_EVENTS = frozenset({"subscription.pending"})


@dataclass(frozen=True)
class WindowVerdict:
    gateway_owns_recovery: bool
    reason: str
    retries_remaining: int

    @property
    def contact_allowed(self) -> bool:
        return not self.gateway_owns_recovery

    @property
    def evidence_line(self) -> str:
        return (
            f"gateway_owns_recovery={self.gateway_owns_recovery} "
            f"retries_remaining={self.retries_remaining}: {self.reason}"
        )


def assess_window(
    subscription_status: str | None,
    days_since_failure: float,
) -> WindowVerdict:
    """Decide whether Razorpay is still auto-retrying this mandate.

    A non-subscription failure (a one-off card payment or an abandoned
    checkout) has no gateway retry ladder at all, so the agent owns it
    immediately.
    """
    status = (subscription_status or "").strip().lower()

    if status == SUBSCRIPTION_HALTED:
        return WindowVerdict(
            gateway_owns_recovery=False,
            reason=(
                "subscription is halted: Razorpay has exhausted its automatic "
                "retries and no longer charges the invoice. Agent-led recovery "
                "is now the only path."
            ),
            retries_remaining=0,
        )

    if status != SUBSCRIPTION_PENDING:
        return WindowVerdict(
            gateway_owns_recovery=False,
            reason=(
                "not a pending mandate charge, so there is no gateway retry "
                "ladder to wait for."
            ),
            retries_remaining=0,
        )

    remaining = sum(1 for day in GATEWAY_RETRY_OFFSETS_DAYS if day > days_since_failure)
    if remaining > 0:
        return WindowVerdict(
            gateway_owns_recovery=True,
            reason=(
                f"subscription is pending {days_since_failure:.1f} days after "
                f"failure; Razorpay will auto-retry {remaining} more time(s) at "
                f"no contact cost. Contacting now spends a scarce contact on a "
                f"charge the provider is about to attempt anyway."
            ),
            retries_remaining=remaining,
        )

    return WindowVerdict(
        gateway_owns_recovery=False,
        reason=(
            "pending subscription past the T+3 auto-retry ladder; the gateway "
            "has effectively finished."
        ),
        retries_remaining=0,
    )


@dataclass(frozen=True)
class MandateComplianceVerdict:
    compliant: bool
    reason: str


def check_pre_debit_notification(
    notification_sent_hours_before_debit: float | None,
) -> MandateComplianceVerdict:
    """RBI requires >= 24h notice before a mandate debit.

    `None` means no notification was sent at all, which is a violation rather
    than an unknown: absence of evidence of notice is absence of notice.
    """
    required = PRE_DEBIT_NOTIFICATION_LEAD.total_seconds() / 3600.0

    if notification_sent_hours_before_debit is None:
        return MandateComplianceVerdict(
            compliant=False,
            reason=(
                "no pre-debit notification recorded; RBI e-mandate rules "
                f"require at least {required:.0f}h notice before any debit."
            ),
        )

    if notification_sent_hours_before_debit < required:
        return MandateComplianceVerdict(
            compliant=False,
            reason=(
                f"pre-debit notification only "
                f"{notification_sent_hours_before_debit:.1f}h before debit; "
                f"RBI requires at least {required:.0f}h."
            ),
        )

    return MandateComplianceVerdict(
        compliant=True,
        reason=(
            f"pre-debit notification sent "
            f"{notification_sent_hours_before_debit:.1f}h before debit."
        ),
    )

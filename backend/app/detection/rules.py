"""Deterministic detection, scoring and prioritisation."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.entities import (
    Customer,
    DataProvenance,
    FailureReason,
    RiskEvent,
    RiskEventType,
)
from app.domain.money import Money

# Base recovery likelihood per failure cause. These are priors used for
# triage ordering only; the reported recovery rate is always measured from
# verified payments, never predicted from these numbers.
BASE_RECOVERY_PROBABILITY: dict[FailureReason, float] = {
    FailureReason.INSUFFICIENT_FUNDS: 0.72,
    FailureReason.CARD_EXPIRED: 0.84,
    FailureReason.CARD_DECLINED: 0.55,
    FailureReason.AUTHENTICATION_FAILED: 0.68,
    FailureReason.TECHNICAL_ERROR: 0.88,
    FailureReason.ABANDONED_CHECKOUT: 0.46,
    FailureReason.INVOICE_UNPAID: 0.61,
    FailureReason.UNKNOWN: 0.40,
}

RECOVERABLE_EVENT_TYPES = frozenset(
    {
        RiskEventType.PAYMENT_FAILED,
        RiskEventType.CHECKOUT_ABANDONED,
        RiskEventType.INVOICE_OVERDUE,
        RiskEventType.SUBSCRIPTION_HALTED,
    }
)


@dataclass(frozen=True)
class RiskSignal:
    event: RiskEvent
    revenue_at_risk: Money
    recovery_probability: float
    priority: float

    @property
    def expected_recoverable_value(self) -> Money:
        return self.revenue_at_risk.scaled(self.recovery_probability)


def recovery_probability(event: RiskEvent, customer: Customer) -> float:
    """Prior likelihood of recovery, clamped to a sane band."""
    p = BASE_RECOVERY_PROBABILITY.get(event.reason, 0.40)
    if customer.opted_out:
        return 0.0
    # Repeated contact attempts within a window depress response rates.
    p *= 1.0 - min(customer.contacts_this_window, 3) * 0.10
    return round(max(0.0, min(p, 0.95)), 4)


def customer_value_factor(customer: Customer) -> float:
    ltv = customer.lifetime_value.paise
    if ltv >= 10_000_000:
        return 1.5
    if ltv >= 2_500_000:
        return 1.25
    if ltv >= 500_000:
        return 1.1
    return 1.0


def urgency_factor(event: RiskEvent, now) -> float:
    """Recovery odds decay with time; recent failures are worth chasing first."""
    age_hours = max(0.0, (now - event.occurred_at).total_seconds() / 3600.0)
    if age_hours <= 1:
        return 1.5
    if age_hours <= 24:
        return 1.2
    if age_hours <= 72:
        return 1.0
    if age_hours <= 168:
        return 0.8
    return 0.6


def priority_score(event: RiskEvent, customer: Customer, now) -> float:
    return round(
        (event.amount.paise / 100.0)
        * recovery_probability(event, customer)
        * customer_value_factor(customer)
        * urgency_factor(event, now),
        4,
    )


def detect(
    events: list[RiskEvent],
    customers: dict[str, Customer],
    now,
) -> list[RiskSignal]:
    """Return recoverable signals, highest priority first."""
    signals: list[RiskSignal] = []
    for event in events:
        if event.event_type not in RECOVERABLE_EVENT_TYPES:
            continue
        customer = customers.get(event.customer_id)
        if customer is None:
            continue
        signals.append(
            RiskSignal(
                event=event,
                revenue_at_risk=event.amount,
                recovery_probability=recovery_probability(event, customer),
                priority=priority_score(event, customer, now),
            )
        )
    # Sort by priority, then event id, so a benchmark run is reproducible.
    signals.sort(key=lambda s: (-s.priority, s.event.id))
    return signals


def total_at_risk(signals: list[RiskSignal]) -> Money:
    out = Money(0)
    for s in signals:
        out = out + s.revenue_at_risk
    return out


def assert_single_provenance(items) -> DataProvenance:
    """Refuse to aggregate live and synthetic records together.

    Reporting a blended number would be a fabrication, so this raises rather
    than picking a winner.
    """
    kinds = {i.provenance for i in items}
    if len(kinds) > 1:
        raise ValueError(f"refusing to mix data provenance: {sorted(kinds)}")
    return kinds.pop() if kinds else DataProvenance.SYNTHETIC

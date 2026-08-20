"""Seeded synthetic dataset generator.

One generator, two profiles. A benchmark that cannot be reproduced exactly is
not evidence, so all randomness derives from an explicit seed (risk R7).
Every record produced is labelled SYNTHETIC.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.domain.entities import (
    Customer,
    DataProvenance,
    FailureReason,
    RiskEvent,
    RiskEventType,
)
from app.domain.money import Money

FAILURE_MIX: list[tuple[FailureReason, float]] = [
    (FailureReason.INSUFFICIENT_FUNDS, 0.28),
    (FailureReason.CARD_EXPIRED, 0.14),
    (FailureReason.CARD_DECLINED, 0.18),
    (FailureReason.AUTHENTICATION_FAILED, 0.12),
    (FailureReason.TECHNICAL_ERROR, 0.08),
    (FailureReason.ABANDONED_CHECKOUT, 0.13),
    (FailureReason.INVOICE_UNPAID, 0.05),
    (FailureReason.UNKNOWN, 0.02),
]

EVENT_TYPE_FOR_REASON = {
    FailureReason.ABANDONED_CHECKOUT: RiskEventType.CHECKOUT_ABANDONED,
    FailureReason.INVOICE_UNPAID: RiskEventType.INVOICE_OVERDUE,
}


@dataclass
class Dataset:
    run_id: str
    seed: int
    customers: dict[str, Customer]
    events: list[RiskEvent]
    generated_at: datetime
    profile: str

    @property
    def provenance(self) -> DataProvenance:
        return DataProvenance.SYNTHETIC


def _weighted_reason(rng: random.Random) -> FailureReason:
    roll = rng.random()
    cumulative = 0.0
    for reason, weight in FAILURE_MIX:
        cumulative += weight
        if roll <= cumulative:
            return reason
    return FAILURE_MIX[-1][0]


def generate(
    n_events: int = 10_000,
    seed: int = 42,
    profile: str = "benchmark",
    opt_out_rate: float = 0.04,
    now: datetime | None = None,
) -> Dataset:
    rng = random.Random(seed)
    now = now or datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
    n_customers = max(1, n_events // 4)

    customers: dict[str, Customer] = {}
    for i in range(n_customers):
        cid = f"cust_{i:06d}"
        customers[cid] = Customer(
            id=cid,
            name=f"Customer {i:06d}",
            email=f"customer{i:06d}@example.invalid",
            contact=f"+9190{i % 100000000:08d}",
            lifetime_value=Money(rng.randint(50_000, 20_000_000)),
            opted_out=rng.random() < opt_out_rate,
            provenance=DataProvenance.SYNTHETIC,
        )

    customer_ids = list(customers)
    events: list[RiskEvent] = []
    for i in range(n_events):
        reason = _weighted_reason(rng)
        # Log-ish spread so a few large failures dominate revenue at risk,
        # which is what real payment data looks like.
        rupees = int(rng.choice([1, 1, 1, 2, 3, 5, 8, 13, 21]) * rng.randint(70, 900))
        events.append(
            RiskEvent(
                id=f"evt_{i:07d}",
                customer_id=rng.choice(customer_ids),
                event_type=EVENT_TYPE_FOR_REASON.get(reason, RiskEventType.PAYMENT_FAILED),
                amount=Money.from_rupees(rupees),
                reason=reason,
                occurred_at=now - timedelta(minutes=rng.randint(0, 60 * 24 * 10)),
                provenance=DataProvenance.SYNTHETIC,
                external_ref=None,
            )
        )

    return Dataset(
        run_id=f"run_{profile}_{seed}_{n_events}",
        seed=seed,
        customers=customers,
        events=events,
        generated_at=now,
        profile=profile,
    )


def demo_dataset() -> Dataset:
    """Small, hand-scaled profile for the live narration."""
    return generate(n_events=40, seed=7, profile="demo")

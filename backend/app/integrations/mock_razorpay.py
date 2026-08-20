"""Deterministic in-process stand-in for Razorpay.

This exists so the whole loop, including the 10,000-event benchmark, can run
with no network and produce byte-identical results on every run. Customer
payment behaviour is derived from a seeded hash of the reference id, so a
given customer behaves the same way under every strategy being compared —
which is what makes an A/B comparison of strategies fair.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.domain.money import Money
from app.integrations.provider import (
    PaymentLinkRequest,
    PaymentLinkResponse,
    ProviderError,
)


def stable_unit_interval(seed: str) -> float:
    """Map a string to a reproducible float in [0, 1)."""
    digest = hashlib.sha256(seed.encode()).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


@dataclass
class _Link:
    id: str
    short_url: str
    status: str
    amount: Money
    reference_id: str


class MockRazorpayProvider:
    name = "mock_razorpay"

    def __init__(self, seed: str = "recoveros", fail_rate: float = 0.0) -> None:
        self.seed = seed
        self.fail_rate = fail_rate
        self._links: dict[str, _Link] = {}
        self.create_calls = 0

    def create_payment_link(self, req: PaymentLinkRequest) -> PaymentLinkResponse:
        self.create_calls += 1
        if self.fail_rate > 0 and stable_unit_interval(
            f"apifail:{self.seed}:{req.reference_id}"
        ) < self.fail_rate:
            raise ProviderError(f"simulated provider error for {req.reference_id}")
        link_id = "plink_" + hashlib.sha256(
            f"{self.seed}:{req.reference_id}".encode()
        ).hexdigest()[:14]
        link = _Link(
            id=link_id,
            short_url="https://rzp.io/i/" + link_id[-8:],
            status="created",
            amount=req.amount,
            reference_id=req.reference_id,
        )
        self._links[link_id] = link
        return PaymentLinkResponse(**link.__dict__)

    def fetch_payment_link(self, link_id: str) -> PaymentLinkResponse:
        link = self._links.get(link_id)
        if link is None:
            raise ProviderError(f"unknown payment link {link_id}")
        return PaymentLinkResponse(**link.__dict__)

    # ---- test-harness affordances (not part of the provider port) ----

    def customer_will_pay(self, reference_id: str, propensity: float) -> bool:
        """Ground truth for the simulation, independent of strategy."""
        return stable_unit_interval(f"pay:{self.seed}:{reference_id}") < propensity

    def paid_event(self, link_id: str) -> dict:
        link = self._links[link_id]
        return {
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {
                    "entity": {
                        "id": link.id,
                        "reference_id": link.reference_id,
                        "amount": link.amount.paise,
                        "status": "paid",
                    }
                },
                "payment": {
                    "entity": {
                        "id": "pay_" + link.id[-12:],
                        "amount": link.amount.paise,
                        "status": "captured",
                    }
                },
            },
        }

    def failed_event(self, link_id: str) -> dict:
        link = self._links[link_id]
        return {
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_" + link.id[-12:],
                        "amount": link.amount.paise,
                        "status": "failed",
                        "notes": {"reference_id": link.reference_id},
                    }
                }
            },
        }

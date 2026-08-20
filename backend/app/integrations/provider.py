"""The payment provider port.

Razorpay sits behind this interface so that the recovery loop can be tested,
benchmarked and demonstrated without a network, and so that a second provider
could be added without touching domain logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain.money import Money


@dataclass(frozen=True)
class PaymentLinkRequest:
    amount: Money
    reference_id: str
    description: str
    customer_name: str
    customer_email: str
    customer_contact: str
    notify_email: bool = True
    notify_sms: bool = False
    reminder_enable: bool = True
    expire_by: int | None = None
    notes: dict | None = None


@dataclass(frozen=True)
class PaymentLinkResponse:
    id: str
    short_url: str
    status: str
    amount: Money
    reference_id: str


class ProviderError(Exception):
    """Any provider-side failure. Never swallowed silently."""


class PaymentProvider(Protocol):
    """The only outbound money-adjacent capability the system has.

    Deliberately narrow: one create call and one read call. A narrow port is
    what makes the blast radius of an agent mistake small.
    """

    name: str

    def create_payment_link(self, req: PaymentLinkRequest) -> PaymentLinkResponse: ...

    def fetch_payment_link(self, link_id: str) -> PaymentLinkResponse: ...

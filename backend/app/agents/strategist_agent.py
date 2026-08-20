"""Strategist agent: chooses WHICH intervention to propose.

The proposal is only a request. It has no authority: the Policy Guard decides,
and the executor refuses to act without an affirmative decision.
"""

from __future__ import annotations

from app.agents.llm import LLMClient
from app.domain.entities import (
    Customer,
    Diagnosis,
    InterventionPlan,
    InterventionType,
    RecoveryCase,
    RiskEventType,
)
from app.domain.states import Actor


class StrategistAgent:
    actor = Actor.STRATEGIST_AGENT

    def __init__(self, llm: LLMClient | None = None, max_discount: float = 10.0) -> None:
        self.llm = llm
        self.max_discount = max_discount

    def plan(
        self,
        case: RecoveryCase,
        diagnosis: Diagnosis,
        customer: Customer,
    ) -> InterventionPlan:
        # An opted-out customer can only ever be left alone. Proposing contact
        # would be denied downstream anyway; refusing to propose it keeps the
        # audit trail honest about intent.
        if customer.opted_out:
            return InterventionPlan(
                intervention=InterventionType.STOP,
                discount_percentage=0.0,
                contact_customer=False,
                rationale="customer opted out of contact; no intervention proposed",
                produced_by=self.actor,
                is_llm_output=False,
            )

        if case.event.event_type is RiskEventType.SUBSCRIPTION_HALTED:
            intervention = InterventionType.SUBSCRIPTION_RECOVERY
            rationale = (
                "Subscription is halted. Razorpay exposes no merchant-callable "
                "retry API, so recovery is a payment link scoped to the unpaid "
                "invoice, reconciled against subscription events."
            )
        elif case.attempts == 0 and diagnosis.recovery_probability >= 0.5:
            intervention = InterventionType.PAYMENT_LINK
            rationale = (
                f"Recovery prior {diagnosis.recovery_probability:.2f} justifies a "
                "direct payment link as the first attempt."
            )
        elif case.attempts == 0:
            intervention = InterventionType.REMINDER
            rationale = (
                f"Recovery prior {diagnosis.recovery_probability:.2f} is low; a "
                "reminder is proportionate before a stronger intervention."
            )
        else:
            intervention = InterventionType.PAYMENT_LINK
            rationale = f"Retry attempt {case.attempts + 1} with a fresh payment link."

        # Discount is only proposed where intent looks weak and value is high
        # enough to justify giving margin away.
        discount = 0.0
        if (
            diagnosis.recovery_probability < 0.5
            and case.revenue_at_risk.paise >= 200_000
            and case.attempts >= 1
        ):
            discount = min(5.0, self.max_discount)
            rationale += " A small discount is proposed to improve conversion."

        return InterventionPlan(
            intervention=intervention,
            discount_percentage=discount,
            contact_customer=intervention is not InterventionType.STOP,
            rationale=rationale,
            produced_by=self.actor,
            is_llm_output=False,
        )

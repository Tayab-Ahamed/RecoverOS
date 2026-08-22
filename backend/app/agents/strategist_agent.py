"""Bounded intervention planning.

The strategist may compare options and propose one. It never authorizes itself:
PolicyEngine remains the only component that can approve an outbound action.
"""

from __future__ import annotations

from app.agents.llm import LLMClient, LLMError
from app.domain.entities import (
    Customer,
    Diagnosis,
    InterventionPlan,
    InterventionType,
    RecoveryCase,
    RiskEventType,
)
from app.domain.states import Actor

SYSTEM = (
    "You are a revenue-recovery strategist. Choose one proportionate intervention "
    "from PAYMENT_LINK, SUBSCRIPTION_RECOVERY, REMINDER, ESCALATION, or STOP. "
    "Use only the evidence supplied. Never override consent, policy, or approval "
    "requirements. Return JSON with intervention, discount_percentage, "
    "contact_customer, rationale, confidence."
)


class StrategistAgent:
    actor = Actor.STRATEGIST_AGENT

    def __init__(self, llm: LLMClient | None = None, max_discount: float = 10.0) -> None:
        self.llm = llm
        self.max_discount = max_discount

    def _rule_proposal(
        self,
        case: RecoveryCase,
        diagnosis: Diagnosis,
        customer: Customer,
    ) -> tuple[InterventionType, float, bool, str, list[str], list[str]]:
        """Create a transparent fallback proposal when no model is configured."""
        if customer.opted_out:
            return (
                InterventionType.STOP,
                0.0,
                False,
                "Customer consent is withdrawn; no contact is proposed.",
                ["STOP: consent boundary"],
                ["PAYMENT_LINK", "REMINDER"],
            )

        reason = case.event.reason
        probability = diagnosis.recovery_probability
        evidence = [
            f"reason={reason}",
            f"recovery_prior={probability:.2f}",
            f"attempts={case.attempts}/{3}",
        ]
        alternatives = ["PAYMENT_LINK", "REMINDER", "ESCALATION"]

        if case.event.event_type is RiskEventType.SUBSCRIPTION_HALTED:
            intervention = InterventionType.SUBSCRIPTION_RECOVERY
            rationale = "Subscription interruption maps to a payment-link recovery for the unpaid amount."
            evidence.append("subscription halted")
        elif reason.name == "INVOICE_UNPAID":
            intervention = InterventionType.REMINDER
            rationale = "Overdue invoice merits a low-friction receivables reminder before escalation."
            evidence.append("invoice overdue")
        elif reason.name == "ABANDONED_CHECKOUT":
            intervention = InterventionType.REMINDER
            rationale = "Checkout intent is unproven; a single light reminder is more proportionate than a discount."
            evidence.append("intent unproven")
        elif reason.name in {"TECHNICAL_ERROR", "AUTHENTICATION_FAILED"}:
            intervention = InterventionType.PAYMENT_LINK
            rationale = "The failure may be transient; a fresh payment route is the highest-signal first action."
            evidence.append("transient failure signal")
        elif reason.name == "CARD_EXPIRED":
            intervention = InterventionType.PAYMENT_LINK
            rationale = "Expired credentials suggest preserved intent; a fresh payment route avoids repeated failure."
            evidence.append("credential refresh needed")
        elif case.attempts == 0 and probability < 0.45:
            intervention = InterventionType.REMINDER
            rationale = "Low recovery prior and no prior attempt justify a gentle reminder before a stronger action."
            evidence.append("low prior / first contact")
        elif case.attempts >= 2:
            intervention = InterventionType.ESCALATION
            rationale = "The attempt budget is nearly exhausted; route the case to a human instead of adding pressure."
            evidence.append("near attempt ceiling")
        else:
            intervention = InterventionType.PAYMENT_LINK
            rationale = "A bounded payment link is the next direct recovery action within the attempt budget."
            evidence.append("within recovery budget")

        discount = 0.0
        if (
            intervention is InterventionType.PAYMENT_LINK
            and probability < 0.5
            and case.revenue_at_risk.paise >= 200_000
            and case.attempts >= 1
        ):
            discount = min(5.0, self.max_discount)
            rationale += " A small discount is proposed only after a prior attempt and above the economic floor."
            evidence.append(f"discount={discount:.1f}%")

        return intervention, discount, intervention not in {InterventionType.ESCALATION, InterventionType.STOP}, rationale, evidence, alternatives

    def plan(
        self,
        case: RecoveryCase,
        diagnosis: Diagnosis,
        customer: Customer,
    ) -> InterventionPlan:
        intervention, discount, contact, rationale, evidence, alternatives = self._rule_proposal(
            case, diagnosis, customer
        )
        confidence = diagnosis.confidence
        used_llm = False

        if self.llm is not None and self.llm.name != "deterministic" and not customer.opted_out:
            try:
                out = self.llm.complete_json(
                    SYSTEM,
                    f"Failure reason: {case.event.reason}. Event type: {case.event.event_type}. "
                    f"Amount: {case.revenue_at_risk}. Recovery probability: "
                    f"{diagnosis.recovery_probability:.3f}. Attempts: {case.attempts}. "
                    f"Contacts: {case.contacts_made}. Lifetime value: {customer.lifetime_value}. "
                    f"Customer opted out: {customer.opted_out}. Diagnosis: {diagnosis.rationale}",
                    '{"intervention": str, "discount_percentage": float, "contact_customer": bool, "rationale": str, "confidence": float}',
                )
                candidate = InterventionType(str(out.get("intervention", "")))
                candidate_discount = float(out.get("discount_percentage", 0.0))
                if candidate_discount < 0 or candidate_discount > self.max_discount:
                    raise ValueError("model discount outside strategist limit")
                if candidate is InterventionType.STOP:
                    candidate_contact = False
                else:
                    candidate_contact = bool(out.get("contact_customer", True))
                candidate_rationale = str(out.get("rationale", "")).strip()
                if not candidate_rationale:
                    raise ValueError("model rationale is empty")
                intervention = candidate
                discount = candidate_discount
                contact = candidate_contact
                rationale = candidate_rationale[:300]
                confidence = max(0.0, min(1.0, float(out.get("confidence", confidence))))
                used_llm = True
            except (LLMError, TypeError, ValueError):
                # Invalid or unavailable model output never becomes an action.
                used_llm = False

        expected = case.revenue_at_risk.scaled(
            diagnosis.recovery_probability * max(0.0, 1.0 - discount / 100.0)
        )
        return InterventionPlan(
            intervention=intervention,
            discount_percentage=discount,
            contact_customer=contact,
            rationale=rationale,
            produced_by=self.actor,
            is_llm_output=used_llm,
            evidence=evidence,
            alternatives_considered=alternatives,
            expected_recovery_value=expected,
            confidence=confidence,
        )

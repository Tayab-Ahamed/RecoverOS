"""Diagnosis agent: explains WHY revenue is at risk.

The numeric recovery prior comes from the deterministic detection layer. The
agent contributes a human-readable causal narrative. This split is deliberate:
the number that drives prioritisation stays reproducible, while the
explanation that helps a human trust the system can be generated.
"""

from __future__ import annotations

from app.agents.llm import LLMClient, LLMError
from app.detection.rules import recovery_probability
from app.domain.entities import Customer, Diagnosis, FailureReason, RiskEvent
from app.domain.states import Actor

SYSTEM = (
    "You are a payments failure analyst. Diagnose only from the supplied evidence. "
    "Return JSON with rationale, confidence, and risk_factors. Never invent payment "
    "states, customer consent, or provider capabilities. Keep the rationale under "
    "240 characters and risk_factors as short strings."
)

CAUSE_NARRATIVE: dict[FailureReason, str] = {
    FailureReason.INSUFFICIENT_FUNDS: (
        "Balance was insufficient at the time of the attempt. Recovery usually "
        "depends on timing rather than intent, so a payment link the customer can "
        "use when funded is appropriate."
    ),
    FailureReason.CARD_EXPIRED: (
        "The stored card has expired. Intent to pay is likely intact, so the "
        "customer needs a route to pay with fresh credentials."
    ),
    FailureReason.CARD_DECLINED: (
        "The issuer declined the charge. The cause is opaque to the merchant, so "
        "offering an alternative payment route is the reasonable next step."
    ),
    FailureReason.AUTHENTICATION_FAILED: (
        "Authentication did not complete. This is commonly a drop-off during 3DS "
        "rather than a refusal to pay."
    ),
    FailureReason.TECHNICAL_ERROR: (
        "A technical error interrupted an otherwise valid attempt. These are the "
        "highest-probability recoveries because nothing about intent changed."
    ),
    FailureReason.ABANDONED_CHECKOUT: (
        "Checkout was abandoned before completion. Intent is unproven, so a light "
        "touch is warranted."
    ),
    FailureReason.INVOICE_UNPAID: (
        "An issued invoice remains unpaid past its due date."
    ),
    FailureReason.UNKNOWN: (
        "The failure cause is not determinable from available evidence. Treated "
        "conservatively."
    ),
}


class DiagnosisAgent:
    actor = Actor.DIAGNOSIS_AGENT

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm

    def diagnose(self, event: RiskEvent, customer: Customer) -> Diagnosis:
        probability = recovery_probability(event, customer)
        rationale = CAUSE_NARRATIVE.get(event.reason, CAUSE_NARRATIVE[FailureReason.UNKNOWN])
        evidence = [f"failure reason={event.reason}", f"amount={event.amount}"]
        risk_factors: list[str] = []
        if customer.opted_out:
            risk_factors.append("customer opted out")
        if customer.contacts_this_window:
            risk_factors.append(f"{customer.contacts_this_window} prior contacts in window")
        if customer.lifetime_value.paise >= 1_000_000:
            risk_factors.append("high lifetime value")
        if event.reason in {FailureReason.TECHNICAL_ERROR, FailureReason.AUTHENTICATION_FAILED}:
            risk_factors.append("failure may be transient")
        used_llm = False
        confidence = probability

        if self.llm is not None and self.llm.name != "deterministic":
            try:
                out = self.llm.complete_json(
                    SYSTEM,
                    f"Failure reason: {event.reason}. Event type: {event.event_type}. "
                    f"Amount: {event.amount}. Customer lifetime value: "
                    f"{customer.lifetime_value}. Opted out: {customer.opted_out}. "
                    f"Contacts in window: {customer.contacts_this_window}.",
                    '{"rationale": str, "confidence": float, "risk_factors": [str]}',
                )
                if isinstance(out.get("rationale"), str) and out["rationale"].strip():
                    rationale = out["rationale"].strip()[:240]
                    used_llm = True
                if isinstance(out.get("confidence"), (float, int)):
                    confidence = max(0.0, min(1.0, float(out["confidence"])))
                if isinstance(out.get("risk_factors"), list):
                    risk_factors = [str(item)[:100] for item in out["risk_factors"][:4]]
            except (LLMError, TypeError, ValueError):
                # The system degrades to a deterministic diagnosis rather than
                # stopping, and the record states that no model output was used.
                used_llm = False

        return Diagnosis(
            cause=event.reason,
            recovery_probability=probability,
            rationale=rationale,
            produced_by=self.actor,
            is_llm_output=used_llm,
            confidence=confidence,
            evidence=evidence,
            risk_factors=risk_factors,
        )

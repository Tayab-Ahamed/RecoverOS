"""Validation of model output, before it can become a proposal.

The trust boundary in this system is stated as "AI proposes, policy authorizes".
That is only true if something stands between the model's raw text and the
proposal object, because a malformed or manipulated response must not reach the
policy engine wearing the costume of a legitimate plan.

This module is that something. It is deterministic, has no model dependency,
and returns structured rejections rather than raising, so a run can *measure*
how often the model produced something unusable instead of discovering it in
production.

Design notes
------------
- Every rejection has a machine-readable `code`. Codes are aggregated in the
  evaluation report, which turns "the LLM is sometimes weird" into a number.
- Bounds are re-checked here even though the policy engine checks them again.
  That duplication is intentional: defence in depth across a trust boundary is
  not redundancy, and the two layers fail for different reasons.
- Injection detection scans the *model's own output* for signs it absorbed
  instructions from case text. It is a detector, not a guarantee; the guarantee
  comes from the policy engine, which does not read rationales at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.entities import InterventionType

MAX_RATIONALE_CHARS = 300
MIN_RATIONALE_CHARS = 12

# Phrases that indicate the model is asserting an outcome it cannot know, or has
# adopted instructions from untrusted case content.
OVERREACH_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bpayment (?:has been|was) (?:captured|received|settled)\b", "claims_capture"),
    (r"\b(?:i|we) (?:have |already )?(?:refunded|charged|debited)\b", "claims_money_moved"),
    (r"\bcustomer (?:has )?consented\b", "claims_consent"),
    (r"\bguarantee(?:d|s)? (?:recovery|payment)\b", "guarantees_outcome"),
    (r"\bignore (?:the |all )?(?:previous|prior|above) instructions\b", "injection_echo"),
    (r"\b(?:policy|limit|ceiling|cap) (?:has been |is )?(?:overridden|waived|lifted)\b", "claims_override"),
    (r"\bapproval (?:is )?not (?:required|needed)\b", "claims_approval_waived"),
    (r"\bskip(?:ping)? (?:the )?(?:approval|policy|review)\b", "requests_bypass"),
)

# Contact details must never be echoed back into a stored rationale.
PII_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"[\w.+-]+@[\w-]+\.[\w.]+", "email_in_rationale"),
    (r"\+?\d[\d\s-]{9,}\d", "phone_in_rationale"),
    (r"\b(?:\d[ -]*?){13,19}\b", "card_in_rationale"),
)


@dataclass(frozen=True)
class Rejection:
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass
class ValidationResult:
    """Either a usable payload, or the reasons it was refused."""

    ok: bool
    payload: dict = field(default_factory=dict)
    rejections: list[Rejection] = field(default_factory=list)

    @property
    def codes(self) -> list[str]:
        return [r.code for r in self.rejections]

    @property
    def summary(self) -> str:
        return "; ".join(str(r) for r in self.rejections) or "accepted"


def _reject(*rejections: Rejection) -> ValidationResult:
    return ValidationResult(ok=False, rejections=list(rejections))


def check_text(text: str) -> list[Rejection]:
    """Scan free text for overreach, absorbed instructions and leaked PII."""
    found: list[Rejection] = []
    lowered = text.lower()
    for pattern, code in OVERREACH_PATTERNS:
        if re.search(pattern, lowered):
            found.append(Rejection(code, f"rationale matched {code}"))
    for pattern, code in PII_PATTERNS:
        if re.search(pattern, text):
            found.append(Rejection(code, f"rationale contains {code}"))
    return found


def _coerce_float(value: object, name: str) -> tuple[float | None, Rejection | None]:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None, Rejection("non_numeric", f"{name} is not a number: {value!r}")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None, Rejection("non_finite", f"{name} is not finite")
    return number, None


def validate_strategy(payload: dict, max_discount: float) -> ValidationResult:
    """Validate a strategist proposal.

    Returns a normalised payload on success. Nothing partially valid is ever
    returned: a proposal is used whole or not at all, because merging a model's
    good fields with fallback values produces a decision no component actually
    made and no one can be held to.
    """
    if not isinstance(payload, dict):
        return _reject(Rejection("not_an_object", "payload is not a JSON object"))

    raw_intervention = payload.get("intervention")
    if not isinstance(raw_intervention, str):
        return _reject(
            Rejection("missing_intervention", f"got {raw_intervention!r}")
        )
    try:
        intervention = InterventionType(raw_intervention.strip().upper())
    except ValueError:
        return _reject(
            Rejection(
                "unknown_intervention",
                f"{raw_intervention!r} is not one of "
                f"{[str(i) for i in InterventionType]}",
            )
        )

    discount, err = _coerce_float(payload.get("discount_percentage", 0.0), "discount")
    if err is not None:
        return _reject(err)
    assert discount is not None
    if discount < 0.0:
        return _reject(Rejection("negative_discount", f"{discount}"))
    if discount > max_discount:
        return _reject(
            Rejection(
                "discount_over_cap",
                f"{discount}% exceeds strategist limit {max_discount}%",
            )
        )

    rationale = payload.get("rationale")
    if not isinstance(rationale, str) or len(rationale.strip()) < MIN_RATIONALE_CHARS:
        return _reject(
            Rejection("empty_rationale", "an unexplained action is not auditable")
        )
    rationale = rationale.strip()[:MAX_RATIONALE_CHARS]

    text_problems = check_text(rationale)
    if text_problems:
        return ValidationResult(ok=False, rejections=text_problems)

    confidence, err = _coerce_float(payload.get("confidence", 0.5), "confidence")
    if err is not None:
        return _reject(err)
    assert confidence is not None
    if not 0.0 <= confidence <= 1.0:
        return _reject(Rejection("confidence_out_of_range", f"{confidence}"))

    contact = payload.get("contact_customer", True)
    if not isinstance(contact, bool):
        return _reject(Rejection("non_bool_contact", f"{contact!r}"))
    # STOP that still contacts the customer is incoherent; refuse rather than
    # quietly repair it, so the incoherence shows up in the metrics.
    if intervention is InterventionType.STOP and contact:
        return _reject(
            Rejection("incoherent_stop", "STOP cannot also contact the customer")
        )

    predicted = payload.get("expected_recovery_probability")
    predicted_p: float | None = None
    if predicted is not None:
        predicted_p, err = _coerce_float(predicted, "expected_recovery_probability")
        if err is not None:
            return _reject(err)
        assert predicted_p is not None
        if not 0.0 <= predicted_p <= 1.0:
            return _reject(
                Rejection("probability_out_of_range", f"{predicted_p}")
            )

    rejected_alternatives = payload.get("alternatives_rejected")
    alternatives: list[str] = []
    if isinstance(rejected_alternatives, list):
        alternatives = [str(a)[:60] for a in rejected_alternatives[:4]]

    return ValidationResult(
        ok=True,
        payload={
            "intervention": intervention,
            "discount_percentage": discount,
            "contact_customer": contact,
            "rationale": rationale,
            "confidence": confidence,
            "expected_recovery_probability": predicted_p,
            "alternatives_rejected": alternatives,
        },
    )


def validate_diagnosis(payload: dict) -> ValidationResult:
    if not isinstance(payload, dict):
        return _reject(Rejection("not_an_object", "payload is not a JSON object"))

    rationale = payload.get("rationale")
    if not isinstance(rationale, str) or len(rationale.strip()) < MIN_RATIONALE_CHARS:
        return _reject(Rejection("empty_rationale", "diagnosis without explanation"))
    rationale = rationale.strip()[:240]

    text_problems = check_text(rationale)
    if text_problems:
        return ValidationResult(ok=False, rejections=text_problems)

    confidence, err = _coerce_float(payload.get("confidence", 0.5), "confidence")
    if err is not None:
        return _reject(err)
    assert confidence is not None
    if not 0.0 <= confidence <= 1.0:
        return _reject(Rejection("confidence_out_of_range", f"{confidence}"))

    probability: float | None = None
    if payload.get("recovery_probability") is not None:
        probability, err = _coerce_float(
            payload["recovery_probability"], "recovery_probability"
        )
        if err is not None:
            return _reject(err)
        assert probability is not None
        if not 0.0 <= probability <= 1.0:
            return _reject(Rejection("probability_out_of_range", f"{probability}"))

    risk_factors = payload.get("risk_factors")
    factors = (
        [str(f)[:100] for f in risk_factors[:4]]
        if isinstance(risk_factors, list)
        else []
    )
    evidence_used = payload.get("evidence_used")
    evidence = (
        [str(e)[:100] for e in evidence_used[:6]]
        if isinstance(evidence_used, list)
        else []
    )

    return ValidationResult(
        ok=True,
        payload={
            "rationale": rationale,
            "confidence": confidence,
            "recovery_probability": probability,
            "risk_factors": factors,
            "evidence_used": evidence,
        },
    )


VERDICTS = frozenset({"ACCEPT", "SOFTEN", "REJECT"})


def validate_critique(payload: dict) -> ValidationResult:
    if not isinstance(payload, dict):
        return _reject(Rejection("not_an_object", "payload is not a JSON object"))

    verdict = payload.get("verdict")
    if not isinstance(verdict, str) or verdict.strip().upper() not in VERDICTS:
        return _reject(Rejection("unknown_verdict", f"{verdict!r}"))
    verdict = verdict.strip().upper()

    reason = payload.get("reason")
    if not isinstance(reason, str) or len(reason.strip()) < MIN_RATIONALE_CHARS:
        return _reject(Rejection("empty_reason", "a veto must be explained"))
    reason = reason.strip()[:MAX_RATIONALE_CHARS]

    text_problems = check_text(reason)
    if text_problems:
        return ValidationResult(ok=False, rejections=text_problems)

    replacement = payload.get("replacement_intervention")
    replacement_type: InterventionType | None = None
    if isinstance(replacement, str) and replacement.strip():
        try:
            replacement_type = InterventionType(replacement.strip().upper())
        except ValueError:
            return _reject(
                Rejection("unknown_intervention", f"replacement {replacement!r}")
            )
    if verdict == "SOFTEN" and replacement_type is None:
        return _reject(
            Rejection("soften_without_replacement", "SOFTEN needs a lighter action")
        )

    remove_discount = payload.get("remove_discount", False)
    if not isinstance(remove_discount, bool):
        return _reject(Rejection("non_bool_remove_discount", f"{remove_discount!r}"))

    confidence, err = _coerce_float(payload.get("confidence", 0.5), "confidence")
    if err is not None:
        return _reject(err)
    assert confidence is not None

    return ValidationResult(
        ok=True,
        payload={
            "verdict": verdict,
            "replacement_intervention": replacement_type,
            "remove_discount": remove_discount,
            "reason": reason,
            "confidence": max(0.0, min(1.0, confidence)),
        },
    )

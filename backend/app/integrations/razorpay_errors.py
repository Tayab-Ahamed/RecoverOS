"""Translation from Razorpay payment error fields to our internal taxonomy.

Why this module exists
----------------------
Everything upstream of here reasons about `FailureReason`, an eight-value
internal enum. Razorpay does not emit that enum. A real `payment.failed`
webhook carries four separate fields, and the recovery decision depends on
all of them:

    error_code         BAD_REQUEST_ERROR | GATEWAY_ERROR | SERVER_ERROR
    error_source       customer | business | bank | gateway | issuer
    error_step         payment_authentication | payment_authorization |
                       payment_initiation | payment_capture
    error_reason       incorrect_otp | payment_failed | ...

The single most important distinction is NOT which of the eight reasons it
maps to. It is whether the decline is *soft* (the same instrument may succeed
later, so a retry is rational) or *hard* (the instrument is dead, so retrying
the same rail burns a contact for nothing and the customer must change
something first).

Getting this wrong in the expensive direction is the classic dunning failure:
retrying a hard decline four times, annoying the customer, and recovering
zero. `error_source` is what makes this decidable, which is why it is part of
the key and not ignored.

Sources: Razorpay Errors > Payments > List of Errors, and the payment entity
error fields documented in the Payments API reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.entities import FailureReason


class DeclineClass(StrEnum):
    """Whether retrying the same instrument can plausibly work."""

    SOFT = "SOFT"
    HARD = "HARD"
    TRANSIENT = "TRANSIENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DeclineVerdict:
    reason: FailureReason
    decline_class: DeclineClass
    same_instrument_retry_ok: bool
    requires_customer_action: bool
    note: str

    @property
    def evidence_line(self) -> str:
        return (
            f"razorpay decline {self.decline_class}: {self.reason} "
            f"(retry_same_instrument={self.same_instrument_retry_ok})"
        )


# Keyed on error_reason, which is the most specific field Razorpay gives.
_BY_REASON: dict[str, tuple[FailureReason, DeclineClass]] = {
    "insufficient_funds": (FailureReason.INSUFFICIENT_FUNDS, DeclineClass.SOFT),
    "payment_failed": (FailureReason.CARD_DECLINED, DeclineClass.SOFT),
    "incorrect_otp": (FailureReason.AUTHENTICATION_FAILED, DeclineClass.SOFT),
    "invalid_otp": (FailureReason.AUTHENTICATION_FAILED, DeclineClass.SOFT),
    "otp_attempts_exceeded": (FailureReason.AUTHENTICATION_FAILED, DeclineClass.SOFT),
    "payment_timeout": (FailureReason.TECHNICAL_ERROR, DeclineClass.TRANSIENT),
    "gateway_technical_error": (FailureReason.TECHNICAL_ERROR, DeclineClass.TRANSIENT),
    "server_error": (FailureReason.TECHNICAL_ERROR, DeclineClass.TRANSIENT),
    "issuer_down": (FailureReason.TECHNICAL_ERROR, DeclineClass.TRANSIENT),
    "card_expired": (FailureReason.CARD_EXPIRED, DeclineClass.HARD),
    "invalid_card_number": (FailureReason.CARD_DECLINED, DeclineClass.HARD),
    "card_blocked": (FailureReason.CARD_DECLINED, DeclineClass.HARD),
    "card_not_enabled_for_online": (FailureReason.CARD_DECLINED, DeclineClass.HARD),
    "international_transaction_not_allowed": (
        FailureReason.CARD_DECLINED,
        DeclineClass.HARD,
    ),
    "payment_cancelled": (FailureReason.ABANDONED_CHECKOUT, DeclineClass.SOFT),
    "payment_pending": (FailureReason.TECHNICAL_ERROR, DeclineClass.TRANSIENT),
}

# Fallback keyed on error_step when error_reason is absent or unrecognised.
_BY_STEP: dict[str, tuple[FailureReason, DeclineClass]] = {
    "payment_authentication": (
        FailureReason.AUTHENTICATION_FAILED,
        DeclineClass.SOFT,
    ),
    "payment_authorization": (FailureReason.CARD_DECLINED, DeclineClass.SOFT),
    "payment_initiation": (FailureReason.TECHNICAL_ERROR, DeclineClass.TRANSIENT),
    "payment_capture": (FailureReason.TECHNICAL_ERROR, DeclineClass.TRANSIENT),
}

# A business-side error is never the customer's problem to fix, and contacting
# them about our own misconfiguration is actively harmful.
_BUSINESS_SOURCES = frozenset({"business", "merchant"})
_INFRA_SOURCES = frozenset({"gateway", "bank", "issuer"})


def classify(
    error_code: str | None = None,
    error_source: str | None = None,
    error_step: str | None = None,
    error_reason: str | None = None,
) -> DeclineVerdict:
    """Map Razorpay error fields onto an actionable verdict.

    Unknown inputs deliberately return UNKNOWN rather than guessing a
    favourable classification. An optimistic default here would manufacture
    retries the evidence does not support.
    """
    reason_key = (error_reason or "").strip().lower()
    step_key = (error_step or "").strip().lower()
    source_key = (error_source or "").strip().lower()
    code_key = (error_code or "").strip().upper()

    mapped = _BY_REASON.get(reason_key) or _BY_STEP.get(step_key)

    if mapped is None:
        if code_key in ("GATEWAY_ERROR", "SERVER_ERROR"):
            mapped = (FailureReason.TECHNICAL_ERROR, DeclineClass.TRANSIENT)
        else:
            mapped = (FailureReason.UNKNOWN, DeclineClass.UNKNOWN)

    reason, decline_class = mapped

    # error_source overrides the step-based guess for infrastructure failures:
    # a bank outage is transient no matter which step reported it.
    if source_key in _INFRA_SOURCES and decline_class is DeclineClass.UNKNOWN:
        decline_class = DeclineClass.TRANSIENT
        reason = FailureReason.TECHNICAL_ERROR

    if source_key in _BUSINESS_SOURCES:
        return DeclineVerdict(
            reason=FailureReason.TECHNICAL_ERROR,
            decline_class=DeclineClass.HARD,
            same_instrument_retry_ok=False,
            requires_customer_action=False,
            note=(
                "error_source=business: our own request was wrong. Fix the "
                "integration; do not contact the customer."
            ),
        )

    retry_ok = decline_class in (DeclineClass.SOFT, DeclineClass.TRANSIENT)
    needs_customer = decline_class is DeclineClass.HARD or reason in (
        FailureReason.INSUFFICIENT_FUNDS,
        FailureReason.CARD_EXPIRED,
        FailureReason.AUTHENTICATION_FAILED,
    )

    if decline_class is DeclineClass.HARD:
        note = (
            "hard decline: the same instrument will fail again. Recovery "
            "requires a different instrument or updated credentials."
        )
    elif decline_class is DeclineClass.TRANSIENT:
        note = (
            "transient infrastructure failure: retry is cheap and needs no "
            "customer contact."
        )
    elif decline_class is DeclineClass.SOFT:
        note = "soft decline: the same instrument may succeed after customer action."
    else:
        note = "unrecognised Razorpay error fields; treated as unknown, not as retryable."

    return DeclineVerdict(
        reason=reason,
        decline_class=decline_class,
        same_instrument_retry_ok=retry_ok,
        requires_customer_action=needs_customer,
        note=note,
    )


def classify_payment_entity(payment: dict) -> DeclineVerdict:
    """Convenience wrapper for a raw Razorpay payment entity from a webhook."""
    return classify(
        error_code=payment.get("error_code"),
        error_source=payment.get("error_source"),
        error_step=payment.get("error_step"),
        error_reason=payment.get("error_reason"),
    )

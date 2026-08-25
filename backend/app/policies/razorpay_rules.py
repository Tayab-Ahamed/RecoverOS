"""Policy rules that exist because of how Razorpay itself behaves.

These are separated from the core policy rules because they are not our
business preferences, they are consequences of the provider's own mechanics
and of RBI regulation. If Razorpay changed its retry ladder, this file would
change and nothing else would.

All three rules read from `case.event.metadata`, which is where provider facts
land when a real webhook is ingested. Synthetic benchmark events carry none of
these keys, so every rule here is inert on synthetic data by design. That is
deliberate and worth stating plainly: these guards protect a live deployment,
and they do not and should not move the synthetic benchmark numbers.
"""

from __future__ import annotations

from app.domain.entities import InterventionPlan, InterventionType, RecoveryCase
from app.integrations.razorpay_catalog import spec_for
from app.integrations.razorpay_gateway_window import (
    assess_window,
    check_pre_debit_notification,
)


def evaluate(
    case: RecoveryCase,
    plan: InterventionPlan,
    contacts_customer: bool,
) -> tuple[list[str], list[str]]:
    """Return (denial reasons, rule ids) from Razorpay-specific constraints."""
    denials: list[str] = []
    rule_ids: list[str] = []
    meta = case.event.metadata or {}

    # Rule 1: do not duplicate the gateway's own free retries.
    if contacts_customer:
        verdict = assess_window(
            subscription_status=meta.get("subscription_status"),
            days_since_failure=float(meta.get("days_since_failure") or 0.0),
        )
        if verdict.gateway_owns_recovery:
            denials.append(verdict.reason)
            rule_ids.append("gateway_owns_retry_window")

    # Rule 2: a mandate debit without 24h notice is non-compliant, not merely
    # impolite. This denies rather than escalates.
    if spec_for(plan.intervention).rbi_pre_debit_notification_required:
        hours = meta.get("pre_debit_notification_hours")
        if meta.get("has_mandate") is True:
            compliance = check_pre_debit_notification(
                None if hours is None else float(hours)
            )
            if not compliance.compliant:
                denials.append(compliance.reason)
                rule_ids.append("rbi_pre_debit_notification")

    # Rule 3: never propose a product the customer is not enrolled in.
    if (
        spec_for(plan.intervention).requires_existing_mandate
        and meta.get("has_mandate") is False
    ):
        denials.append(
            f"{plan.intervention} requires an authorised mandate and this "
            "customer has none; the call would fail at the provider."
        )
        rule_ids.append("requires_existing_mandate")

    # Rule 4: retrying the same instrument after a hard decline burns a
    # contact for a charge that cannot succeed.
    if plan.intervention is not InterventionType.STOP:
        if meta.get("decline_class") == "HARD" and contacts_customer:
            if not bool(meta.get("instrument_updated")):
                denials.append(
                    "hard decline on an unchanged instrument: the same rail "
                    "will fail again, so this contact cannot recover the money."
                )
                rule_ids.append("hard_decline_same_instrument")

    return denials, rule_ids

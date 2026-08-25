"""The Policy Guard.

Architecturally this is the load-bearing component of the whole system. An LLM
proposes an intervention; this module decides whether it is permitted. It is
pure, synchronous and deterministic, takes no LLM input other than the plan
under review, and cannot be bypassed because the executor requires one of its
Decision objects as an argument.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, UTC

from app.domain.entities import (
    Customer,
    InterventionPlan,
    InterventionType,
    RecoveryCase,
    new_id,
)
from app.policies.config import DEFAULT_POLICY, PolicyVersion
from app.policies import razorpay_rules


@dataclass(frozen=True)
class Decision:
    """An authorization verdict. Possession of one with allowed=True is the
    only thing that permits an outbound action."""

    id: str
    allowed: bool
    requires_human_approval: bool
    policy_version_id: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    rule_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def summary(self) -> str:
        verdict = "ALLOW" if self.allowed else "DENY"
        if self.allowed and self.requires_human_approval:
            verdict = "ALLOW_WITH_APPROVAL"
        rules = f" [{','.join(self.rule_ids)}]" if self.rule_ids else ""
        return f"{verdict}{rules}: {'; '.join(self.reasons) or 'no objections'}"


class PolicyEngine:
    """Authorizes or refuses a proposed intervention.

    The clock is injectable. The contact-time-window rule is the only rule that
    depends on the current time, and a rule that reads the wall clock makes the
    verdict depend on when the suite happens to run: a benchmark executed at
    03:00 UTC would deny every contact and silently report different numbers
    than the same benchmark executed at noon. Evaluation runs therefore pass an
    explicit ``now``, so the published figures are a property of the code and
    the seed rather than of the hour of the day.
    """

    def __init__(
        self,
        version: PolicyVersion | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.version = version or DEFAULT_POLICY
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def rules(self):
        return self.version.rules

    def authorize(
        self,
        case: RecoveryCase,
        plan: InterventionPlan,
        customer: Customer,
        now: datetime | None = None,
    ) -> Decision:
        denials: list[str] = []
        rule_ids: list[str] = []
        requires_approval = False

        # STOP is always permitted: the system must never be unable to stop.
        if plan.intervention is InterventionType.STOP:
            return Decision(
                id=new_id("dec"),
                allowed=True,
                requires_human_approval=False,
                policy_version_id=self.version.id,
                reasons=("stop action is unconditionally permitted",),
                rule_ids=("stop_always_allowed",),
            )

        contacts_customer = plan.contact_customer or plan.intervention in (
            InterventionType.PAYMENT_LINK,
            InterventionType.REMINDER,
            InterventionType.SUBSCRIPTION_RECOVERY,
        )

        # Invariant 4: never contact a customer who opted out.
        if self.rules.stop_after_opt_out and customer.opted_out and contacts_customer:
            denials.append("customer has opted out of contact")
            rule_ids.append("stop_after_opt_out")

        # Time-of-day contact window: no outbound contact outside allowed hours.
        if contacts_customer:
            current_hour = (now or self._clock()).hour
            before = self.rules.no_contact_before_hour
            after = self.rules.no_contact_after_hour
            if current_hour < before or current_hour >= after:
                denials.append(
                    f"contact outside allowed hours {before:02d}:00–{after:02d}:00 UTC "
                    f"(current UTC hour: {current_hour:02d})"
                )
                rule_ids.append("contact_time_window")

        # Invariant 3: never exceed the attempt ceiling.
        if case.attempts >= self.rules.max_recovery_attempts:
            denials.append(
                f"attempts {case.attempts} >= max {self.rules.max_recovery_attempts}"
            )
            rule_ids.append("max_recovery_attempts")

        if contacts_customer and case.contacts_made >= self.rules.max_customer_contacts:
            denials.append(
                f"contacts {case.contacts_made} >= max {self.rules.max_customer_contacts}"
            )
            rule_ids.append("max_customer_contacts")

        # Economic floor: chasing trivial amounts costs more than it recovers.
        if case.revenue_at_risk < self.rules.min_recovery_value:
            denials.append(
                f"value {case.revenue_at_risk} below floor {self.rules.min_recovery_value}"
            )
            rule_ids.append("min_recovery_value")

        if plan.discount_percentage > self.rules.max_discount_percentage:
            denials.append(
                f"discount {plan.discount_percentage}% exceeds cap "
                f"{self.rules.max_discount_percentage}%"
            )
            rule_ids.append("max_discount_percentage")

        if self.rules.stop_after_success and case.evidence is not None:
            denials.append("case already has verified payment; further action forbidden")
            rule_ids.append("stop_after_success")

        # High value does not deny; it escalates to a human.
        if (
            self.rules.require_approval_above_threshold
            and case.revenue_at_risk >= self.rules.high_value_threshold
        ):
            requires_approval = True
            rule_ids.append("high_value_manual_review_threshold")

        # Provider-derived and regulatory constraints. Kept in a separate
        # module because they follow from how Razorpay behaves rather than
        # from our own risk appetite.
        rzp_denials, rzp_rule_ids = razorpay_rules.evaluate(
            case, plan, contacts_customer
        )
        denials.extend(rzp_denials)
        rule_ids.extend(rzp_rule_ids)

        if denials:
            return Decision(
                id=new_id("dec"),
                allowed=False,
                requires_human_approval=False,
                policy_version_id=self.version.id,
                reasons=tuple(denials),
                rule_ids=tuple(rule_ids),
            )

        reasons = ["all policy rules satisfied"]
        if requires_approval:
            reasons.append(
                f"value {case.revenue_at_risk} at or above manual review threshold "
                f"{self.rules.high_value_threshold}"
            )
        return Decision(
            id=new_id("dec"),
            allowed=True,
            requires_human_approval=requires_approval,
            policy_version_id=self.version.id,
            reasons=tuple(reasons),
            rule_ids=tuple(rule_ids),
        )

"""Shared test fixtures and a fully wired in-memory system."""

from datetime import UTC, datetime

from app.domain.entities import (
    Customer,
    FailureReason,
    InterventionPlan,
    InterventionType,
    PaymentEvidence,
    RecoveryCase,
    RiskEvent,
    RiskEventType,
    new_id,
    utcnow,
)
from app.domain.money import Money
from app.domain.states import Actor
from app.integrations.idempotency import InMemoryIdempotencyStore
from app.integrations.mock_razorpay import MockRazorpayProvider
from app.policies.engine import PolicyEngine
from app.services.audit import AuditLog
from app.services.executor import RecoveryExecutor
from app.services.orchestrator import RecoveryOrchestrator
from app.services.state_machine import StateMachine
from app.services.verifier import OutcomeVerifier
from app.webhooks.handler import WebhookHandler

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
SECRET = "test_secret"


def customer(**kw) -> Customer:
    defaults = dict(
        id="cust_1",
        name="Test Customer",
        email="test@example.invalid",
        contact="+919000000000",
        lifetime_value=Money.from_rupees(50000),
        opted_out=False,
    )
    defaults.update(kw)
    return Customer(**defaults)


def event(rupees=8499, reason=FailureReason.CARD_EXPIRED, **kw) -> RiskEvent:
    defaults = dict(
        id="evt_1",
        customer_id="cust_1",
        event_type=RiskEventType.PAYMENT_FAILED,
        amount=Money.from_rupees(rupees),
        reason=reason,
        occurred_at=NOW,
    )
    defaults.update(kw)
    return RiskEvent(**defaults)


def case(ev=None, **kw) -> RecoveryCase:
    ev = ev or event()
    defaults = dict(id=new_id("case"), customer_id=ev.customer_id, event=ev)
    defaults.update(kw)
    return RecoveryCase(**defaults)


def plan(intervention=InterventionType.PAYMENT_LINK, discount=0.0, contact=True):
    return InterventionPlan(
        intervention=intervention,
        discount_percentage=discount,
        contact_customer=contact,
        rationale="test",
        produced_by=Actor.STRATEGIST_AGENT,
        is_llm_output=False,
    )


def evidence(paise=849900) -> PaymentEvidence:
    return PaymentEvidence(
        external_payment_id="pay_1",
        external_event_id="evt_1",
        amount=Money(paise),
        captured=True,
        verified_at=utcnow(),
        raw_event_type="payment_link.paid",
    )


class System:
    """The real object graph, with in-memory adapters at the edges."""

    def __init__(self, policy=None, approver=None, seed="test"):
        self.audit = AuditLog()
        self.sm = StateMachine(self.audit)
        self.provider = MockRazorpayProvider(seed=seed)
        self.executor = RecoveryExecutor(self.provider, self.sm, self.audit)
        self.policy = policy or PolicyEngine()
        self.verifier = OutcomeVerifier(self.sm, self.audit)
        self.idempotency = InMemoryIdempotencyStore()
        self.cases: dict[str, RecoveryCase] = {}
        self.outcomes: list[tuple[str, bool]] = []
        self.handler = WebhookHandler(
            secret=SECRET,
            verifier=self.verifier,
            idempotency=self.idempotency,
            case_lookup=self.cases.get,
            on_outcome=lambda case_id, recovered: self.outcomes.append(
                (case_id, recovered)
            ),
        )
        self.orchestrator = RecoveryOrchestrator(
            policy=self.policy,
            executor=self.executor,
            state_machine=self.sm,
            audit=self.audit,
            approver=approver,
        )

    def register(self, c: RecoveryCase) -> RecoveryCase:
        self.cases[c.id] = c
        return c

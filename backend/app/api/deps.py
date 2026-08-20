"""Application wiring.

A single process-wide object graph. The in-memory repositories are the
authoritative store in mock mode, which is what makes the API demonstrable
with no database and no credentials.
"""

from __future__ import annotations

from app.agents.diagnosis_agent import DiagnosisAgent
from app.agents.llm import AnthropicClient, DeterministicLLMClient
from app.agents.strategist_agent import StrategistAgent
from app.core.config import Settings, get_settings
from app.domain.entities import RecoveryCase
from app.integrations.idempotency import InMemoryIdempotencyStore
from app.integrations.mock_razorpay import MockRazorpayProvider
from app.policies.engine import PolicyEngine
from app.repositories.memory import InMemoryCaseRepository, InMemoryCustomerRepository
from app.services.approval import ApprovalService
from app.services.audit import AuditLog
from app.services.executor import RecoveryExecutor
from app.services.orchestrator import RecoveryOrchestrator
from app.services.state_machine import StateMachine
from app.services.verifier import OutcomeVerifier
from app.webhooks.handler import WebhookHandler


def _build_provider(settings: Settings):
    if settings.payment_provider == "razorpay":
        from app.integrations.razorpay import RazorpayProvider

        return RazorpayProvider(
            settings.razorpay_key_id, settings.razorpay_key_secret
        )
    return MockRazorpayProvider(seed="api")


def _build_llm(settings: Settings):
    if settings.llm_provider == "anthropic":
        return AnthropicClient(settings.anthropic_api_key)
    return DeterministicLLMClient()


class Container:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.audit = AuditLog()
        self.state_machine = StateMachine(self.audit)
        self.provider = _build_provider(self.settings)
        self.llm = _build_llm(self.settings)
        self.policy = PolicyEngine()
        self.executor = RecoveryExecutor(self.provider, self.state_machine, self.audit)
        self.verifier = OutcomeVerifier(self.state_machine, self.audit)
        self.cases = InMemoryCaseRepository()
        self.customers = InMemoryCustomerRepository()
        self.idempotency = InMemoryIdempotencyStore()

        self.orchestrator = RecoveryOrchestrator(
            policy=self.policy,
            executor=self.executor,
            state_machine=self.state_machine,
            audit=self.audit,
            diagnosis_agent=DiagnosisAgent(self.llm),
            strategist=StrategistAgent(self.llm),
            # No auto-approver: high-value cases wait for a human.
            approver=None,
        )
        self.approvals = ApprovalService(
            self.policy, self.executor, self.state_machine, self.audit
        )
        self.webhooks = WebhookHandler(
            secret=self.settings.razorpay_webhook_secret or "unset",
            verifier=self.verifier,
            idempotency=self.idempotency,
            case_lookup=self._lookup_case,
        )

    def _lookup_case(self, reference_id: str) -> RecoveryCase | None:
        return self.cases.get(reference_id)


_container: Container | None = None


def get_container() -> Container:
    global _container
    if _container is None:
        _container = Container()
    return _container


def reset_container() -> None:
    """Used by the demo reset endpoint and by tests."""
    global _container
    _container = None

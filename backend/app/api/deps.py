"""Application wiring.

A single process-wide object graph. The in-memory repositories are the
authoritative store in mock mode, which is what makes the API demonstrable
with no database and no credentials.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.agents.diagnosis_agent import DiagnosisAgent
from app.agents.learning_strategist import LearningStrategistAgent
from app.agents.llm import AnthropicClient, DeterministicLLMClient
from app.agents.strategist_agent import StrategistAgent
from app.core.config import ConfigError, Settings, get_settings
from app.core.db import get_session_factory
from app.domain.entities import RecoveryCase
from app.integrations.idempotency import (
    InMemoryIdempotencyStore,
    RedisIdempotencyStore,
    SqlIdempotencyStore,
)
from app.integrations.mock_razorpay import MockRazorpayProvider
from app.models.sql import Base
from app.policies.engine import PolicyEngine
from app.repositories.memory import InMemoryCaseRepository, InMemoryCustomerRepository
from app.repositories.sql import SqlAuditRepository, SqlCaseRepository, SqlCustomerRepository
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
    def __init__(
        self,
        settings: Settings | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if self.settings.is_production:
            raise ConfigError(
                "production boot is blocked until the SQL unit-of-work is wired; "
                "in-memory repositories are permitted only outside production"
            )
        self.audit = AuditLog()
        self.state_machine = StateMachine(self.audit)
        self.provider = _build_provider(self.settings)
        self.llm = _build_llm(self.settings)
        self.policy = PolicyEngine(clock=clock or (lambda: datetime.now(UTC)))
        self.executor = RecoveryExecutor(self.provider, self.state_machine, self.audit)
        self.verifier = OutcomeVerifier(self.state_machine, self.audit)
        self._db_session = None
        if self.settings.database_url:
            self._db_session = get_session_factory()()
            self.cases = SqlCaseRepository(self._db_session)
            self.customers = SqlCustomerRepository(self._db_session)
            self.sql_audit = SqlAuditRepository(self._db_session)
            self.audit.load(self.sql_audit.all())
        else:
            self.cases = InMemoryCaseRepository()
            self.customers = InMemoryCustomerRepository()
            self.sql_audit = None
        if self.settings.is_production:
            self.idempotency = RedisIdempotencyStore(self.settings.redis_url)
        elif self._db_session is not None:
            self.idempotency = SqlIdempotencyStore(self._db_session)
        else:
            self.idempotency = InMemoryIdempotencyStore()

        if self.settings.recovery_strategy == "learning":
            self.strategist = LearningStrategistAgent(
                llm=self.llm,
                seed="api-learning",
                use_critic=True,
                persistence_path=self.settings.bandit_state_path,
            )
        else:
            self.strategist = StrategistAgent(self.llm)

        self.orchestrator = RecoveryOrchestrator(
            policy=self.policy,
            executor=self.executor,
            state_machine=self.state_machine,
            audit=self.audit,
            diagnosis_agent=DiagnosisAgent(self.llm),
            strategist=self.strategist,
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
            on_outcome=getattr(self.strategist, "observe_outcome", None),
        )

    def persist(self) -> None:
        if self._db_session is None:
            return
        self.sql_audit.sync(self.audit.all())
        self._db_session.commit()

    def close(self) -> None:
        if self._db_session is not None:
            self._db_session.close()

    def _lookup_case(self, reference_id: str) -> RecoveryCase | None:
        return self.cases.get(reference_id)


_container: Container | None = None
_clock: Callable[[], datetime] | None = None


def set_clock(clock: Callable[[], datetime] | None) -> None:
    """Inject an explicit clock for tests. None restores the live UTC wall clock."""
    global _clock, _container
    _clock = clock
    if _container is not None:
        reset_container()


def get_container(clock: Callable[[], datetime] | None = None) -> Container:
    global _container
    if _container is None:
        _container = Container(clock=clock or _clock)
    return _container


def restart_container() -> None:
    """Drop the process container while preserving durable database state."""
    global _container
    if _container is not None:
        _container.close()
    _container = None


def reset_container(clock: Callable[[], datetime] | None = None) -> None:
    """Used by the demo reset endpoint and by tests; clears durable demo state."""
    global _container
    if _container is not None:
        # The demo reset must reset durable demo state as well as the process
        # object graph; otherwise re-seeding the same synthetic event IDs
        # violates the database's one-case-per-risk-event invariant.
        if _container._db_session is not None:
            _container._db_session.rollback()
            for table in reversed(Base.metadata.sorted_tables):
                _container._db_session.execute(table.delete())
            _container._db_session.commit()
        _container.close()
    _container = Container(clock=clock or _clock) if (clock is not None or _clock is not None) else None

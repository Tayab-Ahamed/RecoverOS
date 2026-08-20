"""Environment configuration with fail-fast validation.

Deliberately built on the standard library rather than pydantic-settings so
that configuration can be imported and validated in any environment, including
one with no third-party packages installed. See docs/IMPLEMENTATION_DECISIONS.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    pass


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [p.strip() for p in os.getenv(name, default).split(",") if p.strip()]


@dataclass
class Settings:
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "local"))
    app_version: str = field(default_factory=lambda: os.getenv("APP_VERSION", "0.1.0"))
    git_sha: str = field(default_factory=lambda: os.getenv("GIT_SHA", "unknown"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    api_prefix: str = field(default_factory=lambda: os.getenv("API_PREFIX", "/api/v1"))
    cors_origins: list[str] = field(
        default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:5173")
    )

    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))

    razorpay_key_id: str = field(default_factory=lambda: os.getenv("RAZORPAY_KEY_ID", ""))
    razorpay_key_secret: str = field(
        default_factory=lambda: os.getenv("RAZORPAY_KEY_SECRET", "")
    )
    razorpay_webhook_secret: str = field(
        default_factory=lambda: os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    )

    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "mock"))
    anthropic_api_key: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )

    jwt_secret: str = field(default_factory=lambda: os.getenv("JWT_SECRET", ""))

    # provider=mock keeps the whole system runnable with no credentials.
    payment_provider: str = field(
        default_factory=lambda: os.getenv("PAYMENT_PROVIDER", "mock")
    )
    # Guarded local-only affordance for replaying webhooks without a tunnel.
    enable_local_webhook_replay: bool = field(
        default_factory=lambda: _bool("ENABLE_LOCAL_WEBHOOK_REPLAY", False)
    )

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}

    def validate(self) -> None:
        """Fail at boot rather than at the first request."""
        problems: list[str] = []

        if self.payment_provider == "razorpay":
            if not self.razorpay_key_id or not self.razorpay_key_secret:
                problems.append(
                    "PAYMENT_PROVIDER=razorpay requires RAZORPAY_KEY_ID and "
                    "RAZORPAY_KEY_SECRET"
                )
            if not self.razorpay_webhook_secret:
                problems.append(
                    "PAYMENT_PROVIDER=razorpay requires RAZORPAY_WEBHOOK_SECRET; "
                    "unverified webhooks must never be processed"
                )
        elif self.payment_provider != "mock":
            problems.append(f"unknown PAYMENT_PROVIDER {self.payment_provider!r}")

        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            problems.append("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        elif self.llm_provider not in {"mock", "anthropic"}:
            problems.append(f"unknown LLM_PROVIDER {self.llm_provider!r}")

        if self.is_production:
            # Phase 14 production guard: refuse to boot with weak or absent
            # secrets, rather than shipping a default that looks harmless.
            if len(self.jwt_secret) < 32:
                problems.append(
                    "JWT_SECRET must be at least 32 characters in production"
                )
            if self.jwt_secret in {"change-me", "secret", "dev", "insecure"}:
                problems.append("JWT_SECRET is a placeholder value")
            if self.payment_provider == "mock":
                problems.append("PAYMENT_PROVIDER=mock is not permitted in production")
            if self.enable_local_webhook_replay:
                problems.append(
                    "ENABLE_LOCAL_WEBHOOK_REPLAY must be false in production"
                )
            if not self.database_url:
                problems.append("DATABASE_URL is required in production")

        if problems:
            raise ConfigError(
                "invalid configuration:\n  - " + "\n  - ".join(problems)
            )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        s = Settings()
        s.validate()
        _settings = s
    return _settings

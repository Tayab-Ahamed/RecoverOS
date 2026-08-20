"""Liveness and dependency checks.

Dependency checks perform real work: a real query, a real ping, a real API
call. A health endpoint that only returns 200 because the process is alive is
worse than none, because it creates false confidence.

A failing dependency must not prevent the application from booting, so that an
operator can reach the diagnostics.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import get_container
from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "version": settings.app_version,
        "git_sha": settings.git_sha,
        "env": settings.app_env,
        "payment_provider": settings.payment_provider,
        "llm_provider": settings.llm_provider,
    }


@router.get("/health/db")
def health_db(response: Response) -> dict:
    settings = get_settings()
    if not settings.database_url:
        return {"status": "skipped", "detail": "DATABASE_URL is not configured"}
    try:
        from sqlalchemy import text

        from app.core.db import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        response.status_code = 503
        return {"status": "unavailable", "detail": type(exc).__name__}


@router.get("/health/redis")
def health_redis(response: Response) -> dict:
    settings = get_settings()
    if not settings.redis_url:
        return {"status": "skipped", "detail": "REDIS_URL is not configured"}
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_timeout=2)
        client.ping()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        response.status_code = 503
        return {"status": "unavailable", "detail": type(exc).__name__}


@router.get("/health/razorpay")
def health_razorpay(response: Response) -> dict:
    """In mock mode this reports mock rather than pretending to reach Razorpay."""
    container = get_container()
    if container.settings.payment_provider != "razorpay":
        return {"status": "mock", "provider": container.provider.name}
    try:
        container.provider.fetch_payment_link("plink_healthcheck_probe")
        return {"status": "ok", "provider": container.provider.name}
    except Exception as exc:  # noqa: BLE001
        # A 404 for a probe id still proves credentials and reachability.
        message = str(exc)
        if "404" in message or "not found" in message.lower():
            return {"status": "ok", "provider": "razorpay", "detail": "probe rejected"}
        response.status_code = 503
        return {"status": "unavailable", "detail": type(exc).__name__}

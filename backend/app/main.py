"""Application entrypoint.

Health routes are mounted at both the root and the versioned prefix. The root
mount is a deliberate exception to the versioning rule so that orchestrators
and load balancers have a stable, unversioned probe. This deviation is recorded
in docs/IMPLEMENTATION_DECISIONS.md.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import get_container
from app.api.v1 import agents, approvals, benchmark, cases, demo, health, metrics, webhooks
from app.core.config import get_settings
from app.core.errors import classify, error_body
from app.core.logging import configure_logging, get_logger, request_id_var

log = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="RecoverOS",
        version=settings.app_version,
        description=(
            "Autonomous revenue recovery with deterministic governance. "
            "AI proposes, deterministic software authorizes, the payment "
            "provider executes, webhooks verify."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id")
        request_id = incoming or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["x-request-id"] = request_id
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        status, code = classify(exc)
        request_id = request_id_var.get()
        # Full detail to logs, safe shape to the client.
        log.exception("unhandled error", extra={"code": code, "path": request.url.path})
        return JSONResponse(status_code=status, content=error_body(code, request_id))

    prefix = settings.api_prefix

    # Unversioned probe for infrastructure.
    app.include_router(health.router)
    # Versioned surface for clients.
    app.include_router(health.router, prefix=prefix)
    app.include_router(cases.router, prefix=prefix)
    app.include_router(approvals.router, prefix=prefix)
    app.include_router(metrics.router, prefix=prefix)
    app.include_router(benchmark.router, prefix=prefix)
    app.include_router(agents.router, prefix=prefix)
    app.include_router(demo.router, prefix=prefix)
    # Webhooks are provider-facing and intentionally unversioned.
    app.include_router(webhooks.router, prefix="/api")

    @app.on_event("startup")
    def startup() -> None:
        container = get_container()
        log.info(
            "recoveros started",
            extra={
                "version": settings.app_version,
                "env": settings.app_env,
                "payment_provider": container.provider.name,
                "llm_provider": container.llm.name,
                "policy_version": container.policy.version.id,
                "policy_checksum": container.policy.version.checksum,
            },
        )

    return app


app = create_app()

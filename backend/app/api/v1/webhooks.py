"""Provider webhook ingestion.

The raw request body is used for signature verification. Parsing and
re-serialising the JSON would change the bytes and break the digest, so the
body is read once as bytes and passed through untouched.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request, Response

from app.api.deps import get_container
from app.core.logging import get_logger
from app.domain.errors import MissingProviderEventId
from app.webhooks.event_id import is_derived, resolve_event_id

router = APIRouter(tags=["webhooks"])
log = get_logger(__name__)


@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    response: Response,
    x_razorpay_signature: str = Header(default=""),
    x_razorpay_event_id: str = Header(default=""),
) -> dict:
    container = get_container()
    raw = await request.body()

    if not container.settings.razorpay_webhook_secret:
        # Refusing is the only safe behaviour: without a secret, any caller
        # could mark cases as recovered.
        raise HTTPException(503, "webhook secret is not configured")

    # Replay protection is only as strong as this identifier, so it must be
    # durable across process restarts. Deriving one is permitted outside
    # production only, for the signed local replay path. See D11.
    try:
        event_id = resolve_event_id(
            x_razorpay_event_id,
            raw,
            allow_derived=not container.settings.is_production,
        )
    except MissingProviderEventId as exc:
        raise HTTPException(400, "missing provider event id") from exc
    result = container.webhooks.handle(raw, x_razorpay_signature, event_id)
    container.persist()

    log.info(
        "webhook processed",
        extra={
            "accepted": result.accepted,
            "reason": result.reason,
            "event_type": result.event_type,
            "case_id": result.case_id,
            "derived_event_id": is_derived(event_id),
        },
    )

    if not result.accepted and result.reason == "invalid signature":
        # 400 rather than 403, and no detail about what was recognised.
        response.status_code = 400
        return {"accepted": False}

    # Duplicates and unknown references return 200 so the provider stops
    # retrying an event that will never succeed.
    return {
        "accepted": result.accepted,
        "reason": result.reason,
        "case_id": result.case_id,
    }

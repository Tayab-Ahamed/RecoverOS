"""Server-Sent Events endpoint for real-time state streaming."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream")
async def stream_events():
    """Server-Sent Events endpoint that yields a state snapshot every 2 seconds."""

    async def generator():
        from app.api.deps import get_container

        while True:
            container = get_container()
            cases = container.cases.all()
            payload = {
                "type": "state_snapshot",
                "cases": [
                    {
                        "id": c.id,
                        "state": str(c.state),
                        "recovered_amount": (
                            c.recovered_amount.paise if c.recovered_amount else None
                        ),
                    }
                    for c in cases
                ],
            }
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

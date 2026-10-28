import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.services.events import broadcaster

router = APIRouter(tags=["stream"])


@router.get("/stream")
async def stream(request: Request):
    """Server-sent events: change notifications (alerts, defects, readings, features, devices). Clients refetch over REST."""
    q = broadcaster.subscribe()

    async def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broadcaster.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

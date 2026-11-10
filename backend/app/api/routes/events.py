import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.deps import UserDep
from app.services.events import hub

router = APIRouter(tags=["events"])


@router.get("/events")
async def events(request: Request, user: UserDep) -> StreamingResponse:
    """Server-Sent Events: new matches and finished runs for this user, as they are committed."""
    uid = str(user.id)

    async def stream():
        q = hub.subscribe(uid)
        try:
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"  # proxies close idle streams
                    continue
                event.pop("user_id", None)
                yield f"event: {event.get('kind', 'message')}\ndata: {json.dumps(event)}\n\n"
        finally:
            hub.unsubscribe(uid, q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        # no-transform keeps the Next.js proxy from gzip-buffering the stream
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )

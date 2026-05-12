"""SSE router — streams real-time pipeline events to the frontend."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from services.events import subscribe

router = APIRouter()


@router.get("/events")
async def sse_events(request: Request):
    """Server-Sent Events endpoint for real-time pipeline progress.

    Connect with EventSource('/events') from the frontend.
    Events: pipeline.started, pipeline.completed, agent.started,
            agent.completed, agent.progress, agent.tool_call

    Late-joining clients receive up to the last 50 events from the replay
    buffer immediately on connect, so the UI always reflects current state.
    """
    async def event_stream():
        subscriber = subscribe()
        try:
            async for message in subscriber:
                if await request.is_disconnected():
                    break
                yield message
        finally:
            await subscriber.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

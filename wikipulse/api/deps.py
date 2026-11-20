"""Typed FastAPI dependency providers and shared SSE streaming response helper."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from wikipulse.api.cache import SnapshotCache
from wikipulse.api.store import MetricsStore

log = logging.getLogger("wikipulse.api")


def get_store(request: Request) -> MetricsStore:
    return request.app.state.store


def get_cache(request: Request) -> SnapshotCache:
    return request.app.state.cache


def get_sse_interval(request: Request) -> float:
    return request.app.state.sse_interval_s


def sse_response(
    request: Request,
    fetch_payload: Callable[[], Awaitable[dict[str, Any]]],
    interval_s: float,
) -> StreamingResponse:
    """Stream periodic JSON snapshots as Server-Sent Events with graceful error recovery."""

    async def event_generator():
        try:
            while not await request.is_disconnected():
                try:
                    payload = await fetch_payload()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — keep SSE stream alive across Redis blips
                    log.warning("SSE snapshot fetch failed (%s): %s", request.url.path, exc)
                else:
                    yield f"data: {json.dumps(payload, default=str)}\n\n"
                await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

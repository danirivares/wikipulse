"""Async Server-Sent Events (SSE) client for Wikimedia EventStreams."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import httpx

log = logging.getLogger("wikipulse.ingestor.stream")


async def iter_sse_lines(
    client: httpx.AsyncClient,
    url: str,
    *,
    last_event_id: str | None = None,
) -> AsyncIterator[tuple[str | None, str]]:
    """Stream `(event_id, data)` tuples for SSE `message` events from `url`."""
    headers = {"Accept": "text/event-stream"}
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id

    async with client.stream("GET", url, headers=headers) as resp:
        resp.raise_for_status()
        event_type = "message"
        event_id: str | None = last_event_id
        data_lines: list[str] = []

        async for raw_line in resp.aiter_lines():
            line = raw_line.rstrip("\r")
            if not line:
                if data_lines and event_type == "message":
                    yield event_id, "\n".join(data_lines)
                event_type = "message"
                data_lines = []
                continue
            if line.startswith(":"):
                continue  # SSE heartbeat / comment
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "data":
                data_lines.append(value)
            elif field == "event":
                event_type = value or "message"
            elif field == "id":
                event_id = value


async def stream_wikimedia_events(
    url: str,
    user_agent: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    backoff_initial: float = 1.0,
    backoff_cap: float = 30.0,
) -> AsyncIterator[str]:
    """Yield raw JSON event strings forever, reconnecting with exponential backoff."""
    backoff = backoff_initial
    last_id: str | None = None
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)

    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=timeout,
        transport=transport,
    ) as client:
        while True:
            try:
                async for event_id, data in iter_sse_lines(
                    client, url, last_event_id=last_id
                ):
                    if event_id is not None:
                        last_id = event_id
                    backoff = backoff_initial
                    yield data
                log.warning("Wikimedia SSE stream ended; reconnecting in %.1fs", backoff)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("Wikimedia SSE error (%s); reconnecting in %.1fs", exc, backoff)

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, backoff_cap)

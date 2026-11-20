"""GET /api/stream & GET /api/metrics/snapshot — real-time Wikipedia firehose metrics."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from wikipulse.api.cache import SnapshotCache
from wikipulse.api.deps import get_cache, get_sse_interval, get_store, sse_response
from wikipulse.api.store import MetricsStore
from wikipulse.core.redis_keys import ALLOWED_WINDOWS

router = APIRouter()


def _validate_window(window: str) -> str:
    if window not in ALLOWED_WINDOWS:
        raise HTTPException(status_code=400, detail=f"window must be one of {ALLOWED_WINDOWS}")
    return window


@router.get("/metrics/snapshot")
async def metrics_snapshot(
    store: Annotated[MetricsStore, Depends(get_store)],
    cache: Annotated[SnapshotCache, Depends(get_cache)],
    window: str = Query("5m"),
) -> dict[str, Any]:
    _validate_window(window)
    return await cache.get_or_fetch(
        f"metrics:{window}",
        lambda: store.fetch_metrics_snapshot(window),
    )


@router.get("/stream")
async def stream(
    request: Request,
    store: Annotated[MetricsStore, Depends(get_store)],
    cache: Annotated[SnapshotCache, Depends(get_cache)],
    interval_s: Annotated[float, Depends(get_sse_interval)],
    window: str = Query("5m"),
) -> StreamingResponse:
    _validate_window(window)
    return sse_response(
        request,
        lambda: cache.get_or_fetch(
            f"metrics:{window}",
            lambda: store.fetch_metrics_snapshot(window),
        ),
        interval_s,
    )

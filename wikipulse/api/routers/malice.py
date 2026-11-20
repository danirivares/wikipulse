"""GET /api/malice & GET /api/malice/snapshot — live moderation feed and hazard metrics."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from wikipulse.api.cache import SnapshotCache
from wikipulse.api.deps import get_cache, get_sse_interval, get_store, sse_response
from wikipulse.api.store import MetricsStore

router = APIRouter()


@router.get("/malice/snapshot")
async def malice_snapshot(
    store: Annotated[MetricsStore, Depends(get_store)],
    cache: Annotated[SnapshotCache, Depends(get_cache)],
) -> dict[str, Any]:
    return await cache.get_or_fetch("malice", store.fetch_malice_snapshot)


@router.get("/malice")
async def malice(
    request: Request,
    store: Annotated[MetricsStore, Depends(get_store)],
    cache: Annotated[SnapshotCache, Depends(get_cache)],
    interval_s: Annotated[float, Depends(get_sse_interval)],
) -> StreamingResponse:
    return sse_response(
        request,
        lambda: cache.get_or_fetch("malice", store.fetch_malice_snapshot),
        interval_s,
    )

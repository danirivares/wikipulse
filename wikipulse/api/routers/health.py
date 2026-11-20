"""GET /api/health — liveness and Redis readiness check."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from wikipulse.api.deps import get_store
from wikipulse.api.store import MetricsStore

router = APIRouter()


@router.get("/health")
async def health(store: Annotated[MetricsStore, Depends(get_store)]) -> dict[str, str]:
    if not await store.ping():
        raise HTTPException(status_code=503, detail="redis unavailable")
    return {"status": "ok"}

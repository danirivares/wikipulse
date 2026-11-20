"""GET & POST /api/config — read and flip live detection toggles in Redis."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from wikipulse.api.cache import SnapshotCache
from wikipulse.api.deps import get_cache, get_store
from wikipulse.api.store import MetricsStore

router = APIRouter()


class TogglePatch(BaseModel):
    detect_edits: bool | None = None
    detect_images: bool | None = None
    summarize: bool | None = None
    exclude_bots: bool | None = None
    only_anon_new: bool | None = None


@router.get("/config")
async def get_config(
    store: Annotated[MetricsStore, Depends(get_store)],
) -> dict[str, dict[str, bool]]:
    toggles = await store.get_toggles()
    return {"toggles": toggles.to_dict()}


@router.post("/config")
async def update_config(
    patch: TogglePatch,
    store: Annotated[MetricsStore, Depends(get_store)],
    cache: Annotated[SnapshotCache, Depends(get_cache)],
) -> dict[str, dict[str, bool]]:
    toggles = await store.update_toggles(patch.model_dump())
    # Invalidate the malice cache so SSE subscribers see the new toggle state immediately.
    cache.invalidate("malice")
    return {"toggles": toggles.to_dict()}

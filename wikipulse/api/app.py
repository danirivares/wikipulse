"""FastAPI application factory with clean lifespan resource management."""

from __future__ import annotations

from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from wikipulse.api.cache import SnapshotCache
from wikipulse.api.routers import config as config_router
from wikipulse.api.routers import health as health_router
from wikipulse.api.routers import malice as malice_router
from wikipulse.api.routers import stream as stream_router
from wikipulse.api.store import MetricsStore, RedisMetricsStore
from wikipulse.core.config import ApiConfig
from wikipulse.core.logging import configure_logging


def create_app(
    *,
    cfg: ApiConfig | None = None,
    store: MetricsStore | None = None,
) -> FastAPI:
    config = cfg or ApiConfig.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configure_logging(config.log_level)
        managed_store = store is None
        active_store: MetricsStore
        if store is not None:
            active_store = store
        else:
            client = aioredis.Redis(
                host=config.redis.host,
                port=config.redis.port,
                decode_responses=True,
            )
            active_store = RedisMetricsStore(client)

        application.state.store = active_store
        application.state.cache = SnapshotCache(ttl_s=config.cache_ttl_s)
        application.state.sse_interval_s = config.sse_interval_s
        try:
            yield
        finally:
            if managed_store:
                await active_store.aclose()

    application = FastAPI(title="WikiPulse API", version="1.0.0", lifespan=lifespan)
    application.include_router(health_router.router, prefix="/api", tags=["health"])
    application.include_router(stream_router.router, prefix="/api", tags=["stream"])
    application.include_router(malice_router.router, prefix="/api", tags=["malice"])
    application.include_router(config_router.router, prefix="/api", tags=["config"])
    return application


app = create_app()

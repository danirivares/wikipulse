"""Tests for wikipulse.api: SnapshotCache, pipelined RedisMetricsStore, and FastAPI routes."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ResponseError

from tests.conftest import make_mock_redis
from wikipulse.api.app import create_app
from wikipulse.api.cache import SnapshotCache
from wikipulse.api.deps import sse_response
from wikipulse.api.store import RedisMetricsStore, _parse_mrange_breakdown
from wikipulse.core.config import ApiConfig, DetectionToggles, RedisConfig


class _FakeStore:
    def __init__(self) -> None:
        self.toggles = DetectionToggles()
        self.healthy = True
        self.metrics_calls = 0
        self.malice_calls = 0

    async def ping(self) -> bool:
        return self.healthy

    async def fetch_metrics_snapshot(self, window: str) -> dict[str, Any]:
        self.metrics_calls += 1
        return {
            "window": window,
            "timestamp": "2026-11-20T10:00:00+00:00",
            "meta": {"events_per_sec": 25.0, "last_update": "now"},
            "top_articles": [{"title": "Python", "count": 5}],
            "lang_counts": {"enwiki": 40},
            "bot_ratio": {"bot": 10, "human": 30, "ratio": 0.25},
            "anon_ratio": {"anon": 5, "registered": 35, "ratio": 0.125},
            "pulse": [{"ts": 1000, "value": 25.0}],
        }

    async def fetch_malice_snapshot(self) -> dict[str, Any]:
        self.malice_calls += 1
        return {
            "timestamp": 1000,
            "analyzed": 10,
            "flagged_edits": 2,
            "flagged_images": 1,
            "hazard_breakdown": {"S10": 2},
            "recent_analyzed": [],
            "images_analyzed": 3,
            "toggles": self.toggles.to_dict(),
        }

    async def get_toggles(self) -> DetectionToggles:
        return self.toggles

    async def update_toggles(self, patch: dict[str, bool | None]) -> DetectionToggles:
        self.toggles = self.toggles.with_patch(patch)
        return self.toggles

    async def aclose(self) -> None:
        pass


async def test_snapshot_cache_coalesces_concurrent_requests():
    now = 100.0
    cache = SnapshotCache(ttl_s=1.0, clock=lambda: now)
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def gated_fetch() -> dict[str, int]:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"v": calls}

    t1 = asyncio.create_task(cache.get_or_fetch("k", gated_fetch))
    t2 = asyncio.create_task(cache.get_or_fetch("k", gated_fetch))
    t3 = asyncio.create_task(cache.get_or_fetch("k", gated_fetch))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    await asyncio.sleep(0)
    release.set()

    r1, r2, r3 = await asyncio.gather(t1, t2, t3)
    assert calls == 1
    assert r1 == r2 == r3 == {"v": 1}

    # Within TTL -> served from cache.
    now = 100.5
    assert await cache.get_or_fetch("k", gated_fetch) == {"v": 1}
    assert calls == 1

    # Past TTL -> refetched.
    now = 101.2
    assert await cache.get_or_fetch("k", gated_fetch) == {"v": 2}
    assert calls == 2

    # Explicit invalidation -> immediate refetch.
    cache.invalidate("k")
    assert await cache.get_or_fetch("k", gated_fetch) == {"v": 3}


async def test_redis_metrics_store_handles_missing_timeseries_in_pipeline():
    client, _pipe = make_mock_redis(
        execute_return=[
            [("en.wikipedia.org\tPython language", 7.0), ("LegacyPlain", 3.0)],
            {"enwiki": "12"},
            json.dumps({"bot": 2, "human": 10, "ratio": 0.1667}),
            None,
            {
                "events_per_sec": "12.5",
                "last_update": "2026-11-20T10:00:00Z",
            },
            ResponseError("TSDB: the key does not exist"),
        ]
    )

    store = RedisMetricsStore(client)
    snap = await store.fetch_metrics_snapshot("5m")
    assert snap["top_articles"] == [
        {
            "title": "Python language",
            "count": 7,
            "link": "https://en.wikipedia.org/wiki/Python_language",
        },
        {"title": "LegacyPlain", "count": 3, "link": None},
    ]
    assert snap["lang_counts"] == {"enwiki": 12}
    assert snap["pulse"] == []
    assert snap["meta"] == {
        "events_per_sec": 12.5,
        "last_update": "2026-11-20T10:00:00Z",
    }


def test_api_routes_health_snapshots_and_config_cache_invalidation():
    fake = _FakeStore()
    cfg = ApiConfig(redis=RedisConfig(), sse_interval_s=0.05, cache_ttl_s=10.0)
    app = create_app(cfg=cfg, store=fake)

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200

        fake.healthy = False
        assert client.get("/api/health").status_code == 503
        fake.healthy = True

        # Invalid window rejected with 400 on both snapshot and SSE routes.
        assert client.get("/api/metrics/snapshot?window=99m").status_code == 400
        assert client.get("/api/stream?window=99m").status_code == 400

        # Snapshot caching coalesces repeated reads.
        r1 = client.get("/api/metrics/snapshot?window=5m")
        r2 = client.get("/api/metrics/snapshot?window=5m")
        assert r1.status_code == 200
        assert r1.json()["top_articles"] == [{"title": "Python", "count": 5}]
        assert fake.metrics_calls == 1
        assert r2.status_code == 200

        # GET /api/config + POST /api/config invalidates malice cache immediately.
        assert client.get("/api/config").json()["toggles"]["summarize"] is False
        m1 = client.get("/api/malice/snapshot").json()
        assert m1["toggles"]["summarize"] is False
        assert fake.malice_calls == 1

        res = client.post("/api/config", json={"summarize": True, "detect_images": True})
        assert res.status_code == 200
        assert res.json()["toggles"]["summarize"] is True
        assert res.json()["toggles"]["detect_images"] is True

        m2 = client.get("/api/malice/snapshot").json()
        assert m2["toggles"]["summarize"] is True
        assert fake.malice_calls == 2


async def test_redis_metrics_store_fetch_malice_snapshot_and_error_propagation():
    client, pipe = make_mock_redis(
        execute_return=[
            [
                ("ts:hazard:vandalism", [], [(1000, "4")]),
                ("ts:hazard:heur:blanking", [], [(1000, "2")]),
            ],
            [json.dumps({"type": "edit", "title": "Rome", "flagged": True}), "bad-json"],
            {"summarize": "true", "detect_images": "false"},
            [(1000, "25")],
            [(1000, "3")],
            ResponseError("TSDB: the key does not exist"),
            ResponseError("TSDB: the key does not exist"),
        ]
    )

    store = RedisMetricsStore(client)
    snap = await store.fetch_malice_snapshot()
    assert snap["analyzed"] == 25
    assert snap["flagged_edits"] == 3
    assert snap["images_analyzed"] == 0
    assert snap["flagged_images"] == 0
    assert snap["hazard_breakdown"] == {"vandalism": 4, "heur:blanking": 2}
    assert snap["recent_analyzed"] == [{"type": "edit", "title": "Rome", "flagged": True}]
    assert snap["toggles"]["summarize"] is True
    assert snap["toggles"]["detect_images"] is False

    # Dict-shaped TS.MRANGE responses (some Redis client versions) are also parsed.
    assert _parse_mrange_breakdown({"ts:hazard:spam": [{}, [(1000, "7")]]}) == {"spam": 7}

    # Non-ResponseError exceptions propagate cleanly instead of raising TypeError.
    pipe.execute = AsyncMock(
        return_value=[[], {}, None, None, {}, ConnectionError("redis dropped")]
    )
    with pytest.raises(ConnectionError):
        await store.fetch_metrics_snapshot("5m")


async def test_sse_response_streams_frames_and_recovers_from_transient_error():
    checks = 0

    class _FakeRequest:
        url = MagicMock(path="/api/stream")

        async def is_disconnected(self) -> bool:
            nonlocal checks
            checks += 1
            return checks > 3

    attempts = 0

    async def fetch_payload() -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("blip")
        return {"tick": attempts}

    resp = sse_response(_FakeRequest(), fetch_payload, interval_s=0.0)  # type: ignore[arg-type]
    frames = [chunk async for chunk in resp.body_iterator]
    assert frames == ['data: {"tick": 2}\n\n', 'data: {"tick": 3}\n\n']

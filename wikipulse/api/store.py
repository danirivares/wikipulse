"""Pipelined async Redis read/write repository for the API layer."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any, Protocol

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from wikipulse.core.config import DetectionToggles
from wikipulse.core.redis_keys import (
    CONFIG_HASH_KEY,
    META_KEY,
    PULSE_MINUTES,
    RECENT_ANALYZED_KEY,
    TS_EDITS_ANALYZED,
    TS_EVENTS_PER_SEC,
    TS_IMAGES_ANALYZED,
    TS_MALICIOUS_EDITS,
    TS_MALICIOUS_IMAGES,
    TS_RETENTION_MS,
    anon_ratio_key,
    bot_ratio_key,
    lang_counts_key,
    top_articles_key,
)
from wikipulse.core.wiki import build_wiki_url


class MetricsStore(Protocol):
    async def ping(self) -> bool: ...
    async def fetch_metrics_snapshot(self, window: str) -> dict[str, Any]: ...
    async def fetch_malice_snapshot(self) -> dict[str, Any]: ...
    async def get_toggles(self) -> DetectionToggles: ...
    async def update_toggles(self, patch: dict[str, bool | None]) -> DetectionToggles: ...
    async def aclose(self) -> None: ...


def _parse_top_article(member: str, score: float) -> dict[str, Any]:
    count = int(float(score))
    if "\t" in member:
        server_name, title = member.split("\t", 1)
        link = build_wiki_url(server_name, title) or None
        return {"title": title, "count": count, "link": link}
    return {"title": member, "count": count, "link": None}


def _parse_json_or_none(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _unwrap_ts(raw: Any, default: Any) -> Any:
    """Return `default` when a RedisTimeSeries key does not exist; re-raise other errors."""
    if isinstance(raw, ResponseError) and "does not exist" in str(raw):
        return default
    if isinstance(raw, BaseException):
        raise raw
    return raw if raw else default


def _parse_ts_points(raw: Any) -> list[dict[str, int | float]]:
    samples = _unwrap_ts(raw, [])
    return [{"ts": int(ts), "value": float(val)} for ts, val in samples]


def _parse_ts_sum(raw: Any) -> int:
    samples = _unwrap_ts(raw, [])
    return int(sum(float(val) for _, val in samples))


def _parse_mrange_breakdown(raw: Any) -> dict[str, int]:
    series = _unwrap_ts(raw, None)
    if not series:
        return {}
    out: dict[str, int] = {}
    items = series.items() if isinstance(series, dict) else series
    for entry in items:
        if isinstance(series, dict):
            series_key, series_data = entry
            samples = series_data[-1]
        else:
            series_key, _labels, samples = entry
        total = int(sum(float(val) for _, val in samples))
        if total > 0:
            out[str(series_key).removeprefix("ts:hazard:")] = total
    return out


class RedisMetricsStore:
    """Executes snapshot reads in single Redis pipelines (1 RTT per snapshot)."""

    def __init__(self, client: aioredis.Redis) -> None:
        self._client = client

    async def aclose(self) -> None:
        await self._client.aclose()

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except Exception:  # noqa: BLE001
            return False

    async def fetch_metrics_snapshot(self, window: str) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        from_ms = str(now_ms - PULSE_MINUTES * 60_000)
        to_ms = str(now_ms)

        pipe = self._client.pipeline(transaction=False)
        pipe.zrevrange(top_articles_key(window), 0, 9, withscores=True)
        pipe.hgetall(lang_counts_key(window))
        pipe.get(bot_ratio_key(window))
        pipe.get(anon_ratio_key(window))
        pipe.hgetall(META_KEY)
        pipe.execute_command("TS.RANGE", TS_EVENTS_PER_SEC, from_ms, to_ms)
        top_rows, lang_raw, bot_raw, anon_raw, meta_raw, pulse_raw = await pipe.execute(
            raise_on_error=False
        )

        top_rows = [] if isinstance(top_rows, Exception) else top_rows
        lang_raw = {} if isinstance(lang_raw, Exception) else lang_raw
        meta_raw = {} if isinstance(meta_raw, Exception) else meta_raw

        return {
            "window": window,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "meta": {
                "events_per_sec": float(meta_raw.get("events_per_sec", 0.0)),
                "last_update": meta_raw.get("last_update"),
            },
            "top_articles": [_parse_top_article(t, c) for t, c in top_rows],
            "lang_counts": {wiki: int(c) for wiki, c in lang_raw.items()},
            "bot_ratio": _parse_json_or_none(bot_raw),
            "anon_ratio": _parse_json_or_none(anon_raw),
            "pulse": _parse_ts_points(pulse_raw),
        }

    async def fetch_malice_snapshot(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        window_start = now_ms - TS_RETENTION_MS

        pipe = self._client.pipeline(transaction=False)
        pipe.execute_command(
            "TS.MRANGE",
            window_start,
            now_ms,
            "ALIGN",
            "start",
            "AGGREGATION",
            "sum",
            TS_RETENTION_MS,
            "FILTER",
            "kind=hazard",
        )
        pipe.lrange(RECENT_ANALYZED_KEY, 0, 49)
        pipe.hgetall(CONFIG_HASH_KEY)
        for ts_key in (
            TS_EDITS_ANALYZED,
            TS_MALICIOUS_EDITS,
            TS_IMAGES_ANALYZED,
            TS_MALICIOUS_IMAGES,
        ):
            pipe.execute_command(
                "TS.RANGE",
                ts_key,
                window_start,
                now_ms,
                "ALIGN",
                "start",
                "AGGREGATION",
                "sum",
                TS_RETENTION_MS,
            )

        (
            breakdown_raw,
            recent_raw,
            config_raw,
            edits_analyzed_raw,
            flagged_edits_raw,
            images_analyzed_raw,
            flagged_images_raw,
        ) = await pipe.execute(raise_on_error=False)

        recent_analyzed: list[dict[str, Any]] = []
        if not isinstance(recent_raw, Exception):
            for item in recent_raw:
                parsed = _parse_json_or_none(item)
                if parsed is not None:
                    recent_analyzed.append(parsed)

        config_map = {} if isinstance(config_raw, Exception) else config_raw
        toggles = DetectionToggles.from_redis_hash(config_map)

        return {
            "timestamp": int(time.time()),
            "analyzed": _parse_ts_sum(edits_analyzed_raw),
            "flagged_edits": _parse_ts_sum(flagged_edits_raw),
            "flagged_images": _parse_ts_sum(flagged_images_raw),
            "hazard_breakdown": _parse_mrange_breakdown(breakdown_raw),
            "recent_analyzed": recent_analyzed,
            "images_analyzed": _parse_ts_sum(images_analyzed_raw),
            "toggles": toggles.to_dict(),
        }

    async def get_toggles(self) -> DetectionToggles:
        raw = await self._client.hgetall(CONFIG_HASH_KEY)
        return DetectionToggles.from_redis_hash(raw)

    async def update_toggles(self, patch: dict[str, bool | None]) -> DetectionToggles:
        fields = {
            key: ("true" if value else "false")
            for key, value in patch.items()
            if value is not None
        }
        if fields:
            await self._client.hset(CONFIG_HASH_KEY, mapping=fields)
        return await self.get_toggles()

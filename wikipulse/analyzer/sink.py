"""Pipelined async Redis sink for analyzer verdicts, recent feed, and time series."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

import redis.asyncio as aioredis

from wikipulse.analyzer.models import EditAnalysis, ImageAnalysis
from wikipulse.core.redis_keys import (
    ANALYSIS_TTL_S,
    RECENT_ANALYZED_KEY,
    RECENT_FEED_MAX,
    TS_EDITS_ANALYZED,
    TS_IMAGES_ANALYZED,
    TS_MALICIOUS_EDITS,
    TS_MALICIOUS_IMAGES,
    edit_analysis_key,
    hazard_ts_key,
    heuristic_ts_key,
    image_analysis_key,
    ts_add,
)

_HAZARD_LABELS: tuple[str, ...] = ("kind", "hazard")


async def _write_analysis(
    client: aioredis.Redis,
    *,
    key: str,
    hash_fields: dict[str, str],
    feed_entry: dict[str, Any],
    analyzed_ts_key: str,
    malicious_ts_key: str,
    flagged: bool,
    categories: Sequence[str],
    heur_flags: Sequence[str] = (),
) -> None:
    pipe = client.pipeline(transaction=False)
    pipe.hset(key, mapping=hash_fields)
    pipe.expire(key, ANALYSIS_TTL_S)
    ts_add(pipe, analyzed_ts_key, 1, on_duplicate="SUM")
    pipe.lpush(RECENT_ANALYZED_KEY, json.dumps(feed_entry))
    pipe.ltrim(RECENT_ANALYZED_KEY, 0, RECENT_FEED_MAX - 1)

    if flagged:
        ts_add(pipe, malicious_ts_key, 1, on_duplicate="SUM")
        for cat in categories:
            ts_add(pipe, hazard_ts_key(cat), 1, on_duplicate="SUM", labels=_HAZARD_LABELS)
        for flag in heur_flags:
            ts_add(pipe, heuristic_ts_key(flag), 1, on_duplicate="SUM", labels=_HAZARD_LABELS)

    await pipe.execute()


async def write_edit_result(client: aioredis.Redis, analysis: EditAnalysis) -> None:
    await _write_analysis(
        client,
        key=edit_analysis_key(analysis.rev_id),
        hash_fields={
            "title": analysis.title,
            "wiki": analysis.wiki,
            "user": analysis.user,
            "flagged": "1" if analysis.flagged else "0",
            "unsafe": "1" if analysis.unsafe else "0",
            "categories": ",".join(analysis.categories),
            "heur_flags": ",".join(analysis.heur_flags),
            "summary": analysis.summary or "",
            "link": analysis.link,
        },
        feed_entry={
            "type": "edit",
            "rev_id": analysis.rev_id,
            "title": analysis.title,
            "wiki": analysis.wiki,
            "user": analysis.user,
            "flagged": analysis.flagged,
            "categories": analysis.categories,
            "heur_flags": analysis.heur_flags,
            "summary": analysis.summary,
            "link": analysis.link,
            "ts": int(time.time()),
        },
        analyzed_ts_key=TS_EDITS_ANALYZED,
        malicious_ts_key=TS_MALICIOUS_EDITS,
        flagged=analysis.flagged,
        categories=analysis.categories,
        heur_flags=analysis.heur_flags,
    )


async def write_image_result(client: aioredis.Redis, analysis: ImageAnalysis) -> None:
    await _write_analysis(
        client,
        key=image_analysis_key(analysis.title),
        hash_fields={
            "title": analysis.title,
            "wiki": analysis.wiki,
            "user": analysis.user,
            "flagged": "1" if analysis.flagged else "0",
            "unsafe": "1" if analysis.unsafe else "0",
            "categories": ",".join(analysis.categories),
            "summary": analysis.summary or "",
            "link": analysis.link,
        },
        feed_entry={
            "type": "image",
            "title": analysis.title,
            "wiki": analysis.wiki,
            "user": analysis.user,
            "flagged": analysis.flagged,
            "categories": analysis.categories,
            "summary": analysis.summary,
            "link": analysis.link,
            "ts": int(time.time()),
        },
        analyzed_ts_key=TS_IMAGES_ANALYZED,
        malicious_ts_key=TS_MALICIOUS_IMAGES,
        flagged=analysis.flagged,
        categories=analysis.categories,
    )

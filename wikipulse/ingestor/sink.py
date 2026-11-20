"""Pipelined async Redis sink for windowed metrics, live rate telemetry, and candidate streams."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import redis.asyncio as aioredis

from wikipulse.core.redis_keys import (
    DEFAULT_STREAM_MAXLEN,
    META_KEY,
    TS_EVENTS_PER_SEC,
    anon_ratio_key,
    bot_ratio_key,
    lang_counts_key,
    top_articles_key,
    ts_add,
)
from wikipulse.ingestor.windows import WindowSnapshot


class RedisIngestorSink:
    """Materializes all window snapshots and candidate queues in a single Redis pipeline."""

    def __init__(
        self,
        client: aioredis.Redis,
        *,
        edits_stream: str,
        images_stream: str,
        stream_maxlen: int = DEFAULT_STREAM_MAXLEN,
    ) -> None:
        self._client = client
        self._edits_stream = edits_stream
        self._images_stream = images_stream
        self._stream_maxlen = stream_maxlen

    async def flush(
        self,
        *,
        snapshots: list[WindowSnapshot],
        events_per_sec: float,
        edit_candidates: list[dict[str, str]],
        image_candidates: list[dict[str, str]],
    ) -> None:
        now_iso = datetime.now(UTC).isoformat(timespec="seconds")

        pipe = self._client.pipeline(transaction=False)

        for snap in snapshots:
            # Stage into a temporary key and atomically RENAME so concurrent API
            # readers never observe an empty key between DEL and ZADD/HSET.
            zkey = top_articles_key(snap.label)
            if snap.top_articles:
                tmp_zkey = f"{zkey}:tmp"
                pipe.delete(tmp_zkey)
                pipe.zadd(tmp_zkey, {title: float(cnt) for title, cnt in snap.top_articles})
                pipe.rename(tmp_zkey, zkey)
            else:
                pipe.delete(zkey)

            hkey = lang_counts_key(snap.label)
            if snap.lang_counts:
                tmp_hkey = f"{hkey}:tmp"
                pipe.delete(tmp_hkey)
                pipe.hset(
                    tmp_hkey,
                    mapping={wiki: str(cnt) for wiki, cnt in snap.lang_counts.items()},
                )
                pipe.rename(tmp_hkey, hkey)
            else:
                pipe.delete(hkey)

            pipe.set(bot_ratio_key(snap.label), json.dumps(snap.bot_ratio_dict()))
            pipe.set(anon_ratio_key(snap.label), json.dumps(snap.anon_ratio_dict()))

        pipe.hset(
            META_KEY,
            mapping={
                "events_per_sec": f"{round(events_per_sec, 2)}",
                "last_update": now_iso,
            },
        )
        ts_add(pipe, TS_EVENTS_PER_SEC, round(events_per_sec, 4), on_duplicate="LAST")

        for fields in edit_candidates:
            pipe.xadd(
                self._edits_stream,
                fields,
                maxlen=self._stream_maxlen,
                approximate=True,
            )
        for fields in image_candidates:
            pipe.xadd(
                self._images_stream,
                fields,
                maxlen=self._stream_maxlen,
                approximate=True,
            )

        await pipe.execute()

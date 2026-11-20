"""Ingestor service: Wikimedia SSE -> sliding windows + candidate streams -> Redis."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time

import redis.asyncio as aioredis

from wikipulse.core.config import DetectionToggles, IngestorConfig, seed_toggles
from wikipulse.core.logging import configure_logging
from wikipulse.core.redis_keys import CONFIG_HASH_KEY
from wikipulse.ingestor.events import parse_event, select_edit_candidate, select_image_candidate
from wikipulse.ingestor.sink import RedisIngestorSink
from wikipulse.ingestor.stream import stream_wikimedia_events
from wikipulse.ingestor.windows import SlidingWindowAggregator

log = logging.getLogger("wikipulse.ingestor")


class IngestorService:
    """Owns live Wikimedia ingestion, rolling window aggregation, and periodic Redis flushes."""

    def __init__(
        self,
        cfg: IngestorConfig,
        *,
        redis_client: aioredis.Redis | None = None,
        aggregator: SlidingWindowAggregator | None = None,
    ) -> None:
        self._cfg = cfg
        self._owns_redis = redis_client is None
        self._redis = redis_client or aioredis.Redis(
            host=cfg.redis.host, port=cfg.redis.port, decode_responses=True
        )
        self._aggregator = aggregator or SlidingWindowAggregator()
        self._sink = RedisIngestorSink(
            self._redis,
            edits_stream=cfg.edits_stream,
            images_stream=cfg.images_stream,
            stream_maxlen=cfg.stream_maxlen,
        )
        self._toggles: DetectionToggles = cfg.toggles
        self._events_delta = 0
        self._edit_buffer: list[dict[str, str]] = []
        self._image_buffer: list[dict[str, str]] = []
        self._last_flush = time.monotonic()
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def handle_raw_event(self, raw: str) -> None:
        """Parse a single SSE payload, update windows, and buffer matching candidates."""
        event = parse_event(raw)
        if event is None:
            return
        if self._aggregator.record(event):
            self._events_delta += 1

        edit_cand = select_edit_candidate(
            event, self._toggles, sample_rate=self._cfg.sample_rate
        )
        if edit_cand is not None:
            self._edit_buffer.append(edit_cand)

        image_cand = select_image_candidate(
            event, self._toggles, sample_rate=self._cfg.sample_rate
        )
        if image_cand is not None:
            self._image_buffer.append(image_cand)

    async def flush_once(self) -> None:
        """Flush buffered metrics + candidates in one pipeline and refresh live toggles."""
        now_mono = time.monotonic()
        elapsed = now_mono - self._last_flush

        delta = self._events_delta
        edits = self._edit_buffer
        images = self._image_buffer
        self._events_delta = 0
        self._edit_buffer = []
        self._image_buffer = []

        snapshots = self._aggregator.snapshots(int(time.time()))
        events_per_sec = delta / max(elapsed, 0.001)
        try:
            await self._sink.flush(
                snapshots=snapshots,
                events_per_sec=events_per_sec,
                edit_candidates=edits,
                image_candidates=images,
            )
        except Exception:
            # Restore buffered count & most recent candidates so transient Redis
            # failures preserve the rate window and do not drop candidates.
            cap = self._cfg.stream_maxlen
            self._events_delta += delta
            self._edit_buffer = (edits + self._edit_buffer)[-cap:]
            self._image_buffer = (images + self._image_buffer)[-cap:]
            raise
        self._last_flush = now_mono
        raw_toggles = await self._redis.hgetall(CONFIG_HASH_KEY)
        self._toggles = DetectionToggles.from_redis_hash(raw_toggles, base=self._cfg.toggles)

    async def _flush_loop(self) -> None:
        while not self._stop_event.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._cfg.flush_interval_s
                )
            try:
                await self.flush_once()
            except Exception as exc:  # noqa: BLE001
                log.warning("flush failed: %s", exc)

    async def _read_loop(self) -> None:
        async for raw in stream_wikimedia_events(
            self._cfg.wikimedia_url, self._cfg.user_agent
        ):
            if self._stop_event.is_set():
                break
            self.handle_raw_event(raw)

    async def run(self) -> None:
        configure_logging(self._cfg.log_level)
        await seed_toggles(self._redis, self._cfg.toggles)
        self._last_flush = time.monotonic()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, self.stop)

        log.info(
            "ingestor started (url=%s, flush=%.1fs, sample_rate=%.2f)",
            self._cfg.wikimedia_url,
            self._cfg.flush_interval_s,
            self._cfg.sample_rate,
        )

        tasks = [
            asyncio.create_task(self._flush_loop(), name="ingestor-flusher"),
            asyncio.create_task(self._read_loop(), name="ingestor-reader"),
            asyncio.create_task(self._stop_event.wait(), name="ingestor-stop"),
        ]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            self.stop()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with contextlib.suppress(Exception):
                await self.flush_once()
            if self._owns_redis:
                await self._redis.aclose()
            log.info("ingestor stopped")


async def run(cfg: IngestorConfig) -> None:
    await IngestorService(cfg).run()


def main() -> None:
    asyncio.run(run(IngestorConfig.from_env()))


if __name__ == "__main__":
    main()

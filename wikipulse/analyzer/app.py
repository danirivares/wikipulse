"""Concurrent analyzer service: sliding bounded workers over edit and image streams."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable

import redis.asyncio as aioredis

from wikipulse.analyzer.llm import AnalyzerLLM, OpenAIAnalyzerLLM
from wikipulse.analyzer.models import EditCandidate, ImageCandidate
from wikipulse.analyzer.pipeline import process_edit, process_image
from wikipulse.analyzer.ratelimit import AsyncTokenBucket
from wikipulse.analyzer.sink import write_edit_result, write_image_result
from wikipulse.analyzer.wikimedia import Fetcher, WikimediaClient
from wikipulse.core.config import AnalyzerConfig, DetectionToggles, seed_toggles
from wikipulse.core.logging import configure_logging
from wikipulse.core.redis_keys import CONFIG_HASH_KEY

log = logging.getLogger("wikipulse.analyzer")


async def _ensure_group(client: aioredis.Redis, stream: str, group: str) -> None:
    try:
        await client.xgroup_create(stream, group, id="0", mkstream=True)
    except aioredis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def _wait_until_ready_or_stop(
    ready_event: asyncio.Event,
    stop_event: asyncio.Event,
) -> bool:
    """Wait until `ready_event` is set, returning False immediately if `stop_event` fires."""
    if stop_event.is_set():
        return False
    if ready_event.is_set():
        return True
    ready_task = asyncio.create_task(ready_event.wait())
    stop_task = asyncio.create_task(stop_event.wait())
    try:
        await asyncio.wait({ready_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (ready_task, stop_task):
            if not t.done():
                t.cancel()
        await asyncio.gather(ready_task, stop_task, return_exceptions=True)
    return ready_event.is_set() and not stop_event.is_set()


async def _reclaim_pending(
    client: aioredis.Redis,
    *,
    stream: str,
    group: str,
    consumer: str,
    min_idle_ms: int = 60_000,
    count: int = 16,
) -> list[tuple[str, dict[str, str]]]:
    """Reclaim orphaned PEL messages from crashed workers via `XAUTOCLAIM`."""
    try:
        resp = await client.xautoclaim(
            stream, group, consumer, min_idle_time=min_idle_ms, start_id="0-0", count=count
        )
    except Exception as exc:  # noqa: BLE001 — tolerate mocks or older Redis builds
        log.debug("xautoclaim skipped (%s): %s", stream, exc)
        return []
    if not resp or len(resp) < 2:
        return []
    return list(resp[1])


async def consume_stream_loop(
    client: aioredis.Redis,
    *,
    stream: str,
    group: str,
    consumer: str,
    handler: Callable[[dict[str, str]], Awaitable[None]],
    sem: asyncio.Semaphore,
    max_in_flight: int,
    is_enabled: Callable[[], bool],
    ready_event: asyncio.Event,
    stop_event: asyncio.Event,
    block_ms: int = 1000,
    reclaim_idle_ms: int = 60_000,
    backoff_initial_s: float = 0.5,
    backoff_cap_s: float = 10.0,
) -> None:
    """Sliding-window Redis Stream consumer with zero head-of-line blocking and auto-recovery."""
    in_flight: set[asyncio.Task[None]] = set()
    limit = max(1, max_in_flight)
    backoff = backoff_initial_s
    reclaim_checked = False

    async def _handle_one(msg_id: str, fields: dict[str, str]) -> None:
        async with sem:
            try:
                await handler(fields)
            except Exception as exc:  # noqa: BLE001 — isolate failures per candidate
                log.warning("candidate processing failed (%s %s): %s", stream, msg_id, exc)
            finally:
                try:
                    await client.xack(stream, group, msg_id)
                except Exception as exc:  # noqa: BLE001
                    log.warning("xack failed (%s %s): %s", stream, msg_id, exc)

    try:
        while not stop_event.is_set():
            if not await _wait_until_ready_or_stop(ready_event, stop_event):
                break
            if not is_enabled():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=0.5)
                continue

            # Reap completed tasks before checking free capacity.
            done = {t for t in in_flight if t.done()}
            in_flight.difference_update(done)

            if len(in_flight) >= limit:
                stop_waiter = asyncio.create_task(stop_event.wait())
                try:
                    await asyncio.wait(
                        in_flight | {stop_waiter},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    if not stop_waiter.done():
                        stop_waiter.cancel()
                    await asyncio.gather(stop_waiter, return_exceptions=True)
                continue

            free_slots = limit - len(in_flight)
            messages: list[tuple[str, dict[str, str]]] = []
            try:
                if not reclaim_checked:
                    reclaim_checked = True
                    messages = await _reclaim_pending(
                        client,
                        stream=stream,
                        group=group,
                        consumer=consumer,
                        min_idle_ms=reclaim_idle_ms,
                        count=free_slots,
                    )
                if not messages:
                    resp = await client.xreadgroup(
                        group, consumer, {stream: ">"}, count=free_slots, block=block_ms
                    )
                    if resp:
                        messages = [
                            (msg_id, fields)
                            for _stream_name, batch in resp
                            for msg_id, fields in batch
                        ]
                backoff = backoff_initial_s
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — recover from transient Redis errors
                log.warning("stream read failed (%s): %s; retrying in %.1fs", stream, exc, backoff)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=backoff)
                backoff = min(backoff * 2.0, backoff_cap_s)
                continue

            for msg_id, fields in messages:
                task = asyncio.create_task(_handle_one(msg_id, fields))
                in_flight.add(task)
    finally:
        if in_flight:
            await asyncio.gather(*in_flight, return_exceptions=True)


async def monitor_llm_readiness(
    llm: AnalyzerLLM,
    ready_event: asyncio.Event,
    stop_event: asyncio.Event,
    *,
    poll_unready_s: float = 3.0,
    poll_ready_s: float = 10.0,
) -> None:
    """Gate stream consumption on LLM `/health` readiness and log only state transitions."""
    was_ready: bool | None = None
    while not stop_event.is_set():
        ready = await llm.is_ready()
        if ready:
            ready_event.set()
            if was_ready is not True:
                log.info("LLM server is ready; consuming candidates")
        else:
            ready_event.clear()
            if was_ready is not False:
                log.warning("LLM server unavailable; pausing candidate consumption until ready")
        was_ready = ready

        interval = poll_ready_s if ready else poll_unready_s
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=interval)


class AnalyzerService:
    """Owns concurrent edit/image stream consumption, LLM readiness gating, and lifecycle."""

    def __init__(
        self,
        cfg: AnalyzerConfig,
        *,
        redis_client: aioredis.Redis | None = None,
        fetcher: Fetcher | None = None,
        llm: AnalyzerLLM | None = None,
    ) -> None:
        self._cfg = cfg
        self._stack = contextlib.AsyncExitStack()

        if redis_client is None:
            redis_client = aioredis.Redis(
                host=cfg.redis.host, port=cfg.redis.port, decode_responses=True
            )
            self._stack.push_async_callback(redis_client.aclose)
        self._redis = redis_client

        if fetcher is None:
            wiki_client = WikimediaClient(
                user_agent=cfg.user_agent,
                limiter=AsyncTokenBucket(rate_per_min=cfg.max_fetches_per_min),
            )
            self._stack.push_async_callback(wiki_client.aclose)
            self._fetcher: Fetcher = wiki_client
        else:
            self._fetcher = fetcher

        if llm is None:
            openai_llm = OpenAIAnalyzerLLM(
                url=cfg.llm_url,
                model=cfg.llm_model,
                timeout_s=cfg.llm_timeout_s,
                max_connections=cfg.max_concurrency * 2,
            )
            self._stack.push_async_callback(openai_llm.aclose)
            self._llm: AnalyzerLLM = openai_llm
        else:
            self._llm = llm

        self._toggles: DetectionToggles = cfg.toggles
        self._sem = asyncio.Semaphore(cfg.max_concurrency)
        self._llm_ready = asyncio.Event()
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def handle_edit(self, fields: dict[str, str]) -> None:
        toggles = self._toggles
        cand = EditCandidate.from_stream(fields)
        analysis = await process_edit(
            cand,
            fetcher=self._fetcher,
            llm=self._llm,
            detect=toggles.detect_edits,
            summarize=toggles.summarize,
        )
        await write_edit_result(self._redis, analysis)

    async def handle_image(self, fields: dict[str, str]) -> None:
        toggles = self._toggles
        cand = ImageCandidate.from_stream(fields)
        analysis = await process_image(
            cand,
            fetcher=self._fetcher,
            llm=self._llm,
            detect=toggles.detect_images,
            summarize=toggles.summarize,
        )
        await write_image_result(self._redis, analysis)

    async def _refresh_toggles_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                raw = await self._redis.hgetall(CONFIG_HASH_KEY)
                self._toggles = DetectionToggles.from_redis_hash(raw, base=self._cfg.toggles)
            except Exception as exc:  # noqa: BLE001
                log.warning("config refresh failed: %s", exc)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=1.0)

    async def run(self) -> None:
        configure_logging(self._cfg.log_level)
        await _ensure_group(self._redis, self._cfg.edits_stream, self._cfg.consumer_group)
        await _ensure_group(self._redis, self._cfg.images_stream, self._cfg.image_consumer_group)
        await seed_toggles(self._redis, self._cfg.toggles)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, self.stop)

        log.info(
            "analyzer started (model=%s, url=%s, concurrency=%d, detect_edits=%s, "
            "detect_images=%s, summarize=%s)",
            self._cfg.llm_model,
            self._cfg.llm_url,
            self._cfg.max_concurrency,
            self._cfg.toggles.detect_edits,
            self._cfg.toggles.detect_images,
            self._cfg.toggles.summarize,
        )

        tasks = [
            asyncio.create_task(self._refresh_toggles_loop(), name="analyzer-config"),
            asyncio.create_task(
                monitor_llm_readiness(self._llm, self._llm_ready, self._stop_event),
                name="analyzer-llm",
            ),
            asyncio.create_task(
                consume_stream_loop(
                    self._redis,
                    stream=self._cfg.edits_stream,
                    group=self._cfg.consumer_group,
                    consumer=self._cfg.consumer_name,
                    handler=self.handle_edit,
                    sem=self._sem,
                    max_in_flight=self._cfg.max_concurrency,
                    is_enabled=lambda: self._toggles.detect_edits or self._toggles.summarize,
                    ready_event=self._llm_ready,
                    stop_event=self._stop_event,
                ),
                name="analyzer-edits",
            ),
            asyncio.create_task(
                consume_stream_loop(
                    self._redis,
                    stream=self._cfg.images_stream,
                    group=self._cfg.image_consumer_group,
                    consumer=self._cfg.consumer_name,
                    handler=self.handle_image,
                    sem=self._sem,
                    max_in_flight=self._cfg.max_concurrency,
                    is_enabled=lambda: self._toggles.detect_images or self._toggles.summarize,
                    ready_event=self._llm_ready,
                    stop_event=self._stop_event,
                ),
                name="analyzer-images",
            ),
            asyncio.create_task(self._stop_event.wait(), name="analyzer-stop"),
        ]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            self.stop()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._stack.aclose()
            log.info("analyzer stopped")


async def run(cfg: AnalyzerConfig) -> None:
    await AnalyzerService(cfg).run()


def main() -> None:
    asyncio.run(run(AnalyzerConfig.from_env()))


if __name__ == "__main__":
    main()

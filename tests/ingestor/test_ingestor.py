"""Tests for wikipulse.ingestor: SSE parsing, reconnect, candidate selection, windows, sink."""

from __future__ import annotations

import json
import random
from unittest.mock import AsyncMock

import httpx
import pytest

from wikipulse.core.config import DetectionToggles, IngestorConfig, RedisConfig
from wikipulse.core.redis_keys import META_KEY, lang_counts_key, top_articles_key
from wikipulse.ingestor import stream as stream_mod
from wikipulse.ingestor.app import IngestorService
from wikipulse.ingestor.events import parse_event, select_edit_candidate, select_image_candidate
from wikipulse.ingestor.sink import RedisIngestorSink
from wikipulse.ingestor.stream import iter_sse_lines, stream_wikimedia_events
from wikipulse.ingestor.windows import RollingWindow, SlidingWindowAggregator


def _raw_edit(**overrides) -> str:
    base = {
        "type": "edit",
        "namespace": 0,
        "wiki": "enwiki",
        "server_name": "en.wikipedia.org",
        "title": "Python",
        "user": "Alice",
        "bot": False,
        "comment": "Fix link",
        "length": {"old": 1200, "new": 1250},
        "revision": {"old": 100, "new": 101},
        "meta": {"dt": "2026-11-20T10:00:00Z"},
    }
    base.update(overrides)
    return json.dumps(base)


def test_parse_event_handles_valid_and_malformed():
    assert parse_event("not json") is None
    assert parse_event("[]") is None
    assert parse_event("{}") is None

    ev = parse_event(_raw_edit(user="~2026-99-1"))
    assert ev is not None
    assert ev.is_edit is True
    assert ev.is_article is True
    assert ev.is_anon is True
    assert ev.rev_old == 100
    assert ev.rev_new == 101


def test_select_edit_and_image_candidates_respect_toggles():
    ev = parse_event(_raw_edit(user="~2026-99-1", comment=""))
    assert ev is not None

    toggles_off = DetectionToggles(detect_edits=False, summarize=False)
    assert select_edit_candidate(ev, toggles_off) is None

    toggles_on = DetectionToggles(detect_edits=True, only_anon_new=True)
    cand = select_edit_candidate(ev, toggles_on)
    assert cand is not None
    assert cand["anon"] == "1"
    assert cand["heur_flags"] == "no_comment"

    bot_ev = parse_event(_raw_edit(bot=True))
    assert bot_ev is not None
    assert select_edit_candidate(bot_ev, DetectionToggles(exclude_bots=True)) is None

    # Sampling at 0.0 drops everything deterministically.
    assert select_edit_candidate(ev, toggles_on, sample_rate=0.0, rng=random.Random(1)) is None

    upload = parse_event(
        _raw_edit(
            type="log",
            log_type="upload",
            namespace=6,
            title="File:Example.jpg",
            wiki="commonswiki",
        )
    )
    assert upload is not None
    assert select_image_candidate(upload, DetectionToggles(detect_images=False)) is None
    img = select_image_candidate(upload, DetectionToggles(detect_images=True))
    assert img is not None
    assert img["title"] == "File:Example.jpg"

    pdf_upload = parse_event(
        _raw_edit(
            type="log",
            log_type="upload",
            namespace=6,
            title="File:Scan_1873.pdf",
            wiki="commonswiki",
        )
    )
    assert pdf_upload is not None
    assert select_image_candidate(pdf_upload, DetectionToggles(detect_images=True)) is None


def test_rolling_window_exact_sliding_late_drop_and_eviction():
    win = RollingWindow("1m", 60)
    t0 = 1_760_000_000

    e1 = parse_event(
        _raw_edit(title="Alpha", wiki="enwiki", bot=False, meta={"dt": ""}, timestamp=t0)
    )
    e2 = parse_event(
        _raw_edit(
            title="Alpha",
            wiki="eswiki",
            bot=True,
            user="~2026-1-1",
            meta={"dt": ""},
            timestamp=t0 + 10,
        )
    )
    e3 = parse_event(
        _raw_edit(title="Q42", wiki="wikidatawiki", bot=True, meta={"dt": ""}, timestamp=t0 + 20)
    )
    late = parse_event(
        _raw_edit(title="Stale", wiki="frwiki", meta={"dt": ""}, timestamp=t0 - 100)
    )
    assert e1 and e2 and e3 and late

    win.record(e1)
    win.record(e2)
    win.record(e3)
    win.record(late)  # Outside [high_watermark - 60, high_watermark] -> ignored

    snap1 = win.snapshot(t0 + 30)
    assert snap1.top_articles == [("en.wikipedia.org\tAlpha", 2)]  # wikidatawiki excluded
    assert snap1.lang_counts == {"enwiki": 1, "eswiki": 1, "wikidatawiki": 1}
    assert snap1.bot == 2 and snap1.human == 1
    assert snap1.anon == 1 and snap1.registered == 2
    assert snap1.bot_ratio_dict()["ratio"] == round(2 / 3, 4)

    # Advance past t0 + 60 -> bucket at t0 expires.
    snap2 = win.snapshot(t0 + 65)
    assert snap2.top_articles == [("en.wikipedia.org\tAlpha", 1)]
    assert "enwiki" not in snap2.lang_counts
    assert snap2.bot == 2 and snap2.human == 0
    assert win.active_buckets == 2

    # Advance past all buckets -> completely empty & zero memory leak.
    snap3 = win.snapshot(t0 + 200)
    assert snap3.top_articles == []
    assert snap3.lang_counts == {}
    assert win.active_buckets == 0


def test_sliding_window_aggregator_ignores_uploads():
    agg = SlidingWindowAggregator({"1m": 60, "5m": 300})
    edit = parse_event(_raw_edit(meta={"dt": ""}, timestamp=1000))
    upload = parse_event(_raw_edit(type="log", log_type="upload", meta={"dt": ""}, timestamp=1000))
    assert edit and upload
    assert agg.record(edit) is True
    assert agg.record(upload) is False
    snaps = agg.snapshots(1010)
    assert len(snaps) == 2
    assert snaps[0].top_articles == [("en.wikipedia.org\tPython", 1)]


async def test_iter_sse_lines_parses_events_and_ids():
    sse_body = (
        ": heartbeat\n"
        "id: evt-1\n"
        "event: message\n"
        'data: {"hello": 1}\n'
        "\n"
        "event: ping\n"
        "data: ignore-me\n"
        "\n"
        "id: evt-2\n"
        "data: line1\n"
        "data: line2\n"
        "\n"
    )
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(dict(request.headers))
        return httpx.Response(200, text=sse_body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = [
            item
            async for item in iter_sse_lines(
                client, "https://example.test/sse", last_event_id="prev"
            )
        ]

    assert seen_headers["last-event-id"] == "prev"
    assert items == [("evt-1", '{"hello": 1}'), ("evt-2", "line1\nline2")]


async def test_stream_wikimedia_events_reconnects_with_last_event_id_and_backoff(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(stream_mod.asyncio, "sleep", fake_sleep)

    attempts = 0
    seen_last_ids: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        seen_last_ids.append(request.headers.get("last-event-id"))
        if attempts == 1:
            return httpx.Response(200, text="id: e1\ndata: first\n\n")
        if attempts == 2:
            raise httpx.ConnectError("network drop")
        return httpx.Response(200, text="id: e2\ndata: second\n\n")

    received: list[str] = []
    stream = stream_wikimedia_events(
        "https://example.test/sse",
        "WikiPulse-Test/1.0",
        transport=httpx.MockTransport(handler),
        backoff_initial=1.0,
        backoff_cap=4.0,
    )
    async for raw in stream:
        received.append(raw)
        if len(received) == 2:
            break
    await stream.aclose()

    assert received == ["first", "second"]
    assert seen_last_ids == [None, "e1", "e1"]
    assert sleeps == [1.0, 2.0]


async def test_redis_ingestor_sink_atomic_swap_and_empty_delete(mock_redis):
    client, pipe = mock_redis
    agg = SlidingWindowAggregator({"1m": 60})
    ev = parse_event(_raw_edit(meta={"dt": ""}, timestamp=1000))
    assert ev is not None
    agg.record(ev)

    sink = RedisIngestorSink(
        client, edits_stream="stream:cand:edits", images_stream="stream:cand:images"
    )
    await sink.flush(
        snapshots=agg.snapshots(1005),
        events_per_sec=5.0,
        edit_candidates=[{"rev_new": "101"}],
        image_candidates=[{"title": "File:A.png"}],
    )

    zkey = top_articles_key("1m")
    hkey = lang_counts_key("1m")
    pipe.delete.assert_any_call(f"{zkey}:tmp")
    pipe.zadd.assert_called_once()
    pipe.rename.assert_any_call(f"{zkey}:tmp", zkey)
    pipe.rename.assert_any_call(f"{hkey}:tmp", hkey)
    pipe.hincrby.assert_not_called()
    meta_calls = [c for c in pipe.hset.call_args_list if c.args and c.args[0] == META_KEY]
    assert len(meta_calls) == 1
    assert meta_calls[0].kwargs["mapping"]["events_per_sec"] == "5.0"
    assert pipe.xadd.call_count == 2
    pipe.execute.assert_awaited_once()

    # Empty snapshot clears live keys directly instead of staging empty temp keys.
    pipe.reset_mock()
    await sink.flush(
        snapshots=agg.snapshots(2000),
        events_per_sec=0.0,
        edit_candidates=[],
        image_candidates=[],
    )
    pipe.delete.assert_any_call(zkey)
    pipe.delete.assert_any_call(hkey)
    pipe.rename.assert_not_called()
    pipe.hincrby.assert_not_called()


async def test_ingestor_service_flushes_and_applies_refreshed_toggles(mock_redis):
    client, pipe = mock_redis
    client.hgetall = AsyncMock(return_value={"detect_edits": "false", "detect_images": "true"})

    cfg = IngestorConfig(redis=RedisConfig(), toggles=DetectionToggles())
    svc = IngestorService(cfg, redis_client=client)

    svc.handle_raw_event(_raw_edit(title="Berlin"))
    svc.handle_raw_event("not-json")
    await svc.flush_once()

    pipe.hincrby.assert_not_called()
    meta_calls = [c for c in pipe.hset.call_args_list if c.args and c.args[0] == META_KEY]
    assert len(meta_calls) == 1
    assert float(meta_calls[0].kwargs["mapping"]["events_per_sec"]) > 0.0
    assert pipe.xadd.call_count == 1

    # After refresh, detect_edits=false and detect_images=true take effect on subsequent events.
    pipe.reset_mock()
    svc.handle_raw_event(_raw_edit(title="Paris"))
    svc.handle_raw_event(
        _raw_edit(
            type="log",
            log_type="upload",
            namespace=6,
            title="File:Photo.jpg",
            wiki="commonswiki",
        )
    )
    await svc.flush_once()

    assert pipe.xadd.call_count == 1
    assert pipe.xadd.call_args.args[0] == cfg.images_stream


async def test_ingestor_service_recovers_buffered_data_after_transient_flush_error(mock_redis):
    client, pipe = mock_redis
    client.hgetall = AsyncMock(return_value={})
    pipe.execute = AsyncMock(side_effect=[ConnectionError("redis down"), []])

    cfg = IngestorConfig(redis=RedisConfig(), toggles=DetectionToggles(), stream_maxlen=2)
    svc = IngestorService(cfg, redis_client=client)

    svc.handle_raw_event(_raw_edit(title="A", revision={"old": 1, "new": 2}))
    svc.handle_raw_event(_raw_edit(title="B", revision={"old": 2, "new": 3}))
    svc.handle_raw_event(_raw_edit(title="C", revision={"old": 3, "new": 4}))

    with pytest.raises(ConnectionError):
        await svc.flush_once()

    # Next flush preserves the event rate window and delivers the newest `stream_maxlen` candidates.
    pipe.reset_mock(side_effect=False)
    await svc.flush_once()

    pipe.hincrby.assert_not_called()
    meta_calls = [c for c in pipe.hset.call_args_list if c.args and c.args[0] == META_KEY]
    assert len(meta_calls) == 1
    assert float(meta_calls[0].kwargs["mapping"]["events_per_sec"]) > 0.0
    emitted_titles = [call.args[1]["title"] for call in pipe.xadd.call_args_list]
    assert emitted_titles == ["B", "C"]

"""Tests for wikipulse.analyzer: Wikimedia client, Gemma 4 JSON client, pipeline, concurrency."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from wikipulse.analyzer import ratelimit as ratelimit_mod
from wikipulse.analyzer import wikimedia as wikimedia_mod
from wikipulse.analyzer.app import AnalyzerService, consume_stream_loop, monitor_llm_readiness
from wikipulse.analyzer.llm import OpenAIAnalyzerLLM, parse_llm_json
from wikipulse.analyzer.models import EditCandidate, ImageCandidate, LLMResult
from wikipulse.analyzer.pipeline import _format_exc, process_edit, process_image
from wikipulse.analyzer.prompts import (
    MAX_ADDED_CHARS,
    MAX_REMOVED_CHARS,
    build_edit_user_prompt,
    build_response_format,
)
from wikipulse.analyzer.ratelimit import AsyncTokenBucket
from wikipulse.analyzer.sink import write_edit_result, write_image_result
from wikipulse.analyzer.wikimedia import WikimediaClient, extract_diff_text
from wikipulse.core.config import AnalyzerConfig, DetectionToggles, RedisConfig
from wikipulse.core.redis_keys import (
    RECENT_ANALYZED_KEY,
    TS_EDITS_ANALYZED,
    TS_IMAGES_ANALYZED,
    TS_MALICIOUS_EDITS,
    edit_analysis_key,
    hazard_ts_key,
    heuristic_ts_key,
    image_analysis_key,
)


class _FakeFetcher:
    def __init__(
        self,
        *,
        added: str = "",
        removed: str = "",
        image: tuple[bytes, str] = (b"", ""),
    ) -> None:
        self._added = added
        self._removed = removed
        self._image = image

    async def fetch_diff(self, server_name: str, old_rev: int, new_rev: int) -> tuple[str, str]:
        return self._added, self._removed

    async def fetch_thumbnail(
        self, server_name: str, file_title: str, width: int = 512
    ) -> tuple[bytes, str]:
        return self._image


class _FakeAnalyzerLLM:
    """Deterministic in-memory `AnalyzerLLM` test double."""

    def __init__(
        self,
        result: LLMResult | None = None,
        *,
        ready: bool = True,
        error: Exception | None = None,
    ) -> None:
        self._result = result or LLMResult()
        self._error = error
        self.ready = ready
        self.edit_calls: list[dict[str, Any]] = []
        self.image_calls: list[dict[str, Any]] = []

    async def is_ready(self) -> bool:
        return self.ready

    async def analyze_edit(
        self,
        *,
        title: str,
        removed: str,
        added: str,
        detect: bool,
        summarize: bool,
    ) -> LLMResult:
        self.edit_calls.append(
            {
                "title": title,
                "removed": removed,
                "added": added,
                "detect": detect,
                "summarize": summarize,
            }
        )
        if self._error is not None:
            raise self._error
        return self._result

    async def analyze_image(
        self,
        *,
        image_bytes: bytes,
        mime: str,
        title: str,
        detect: bool,
        summarize: bool,
    ) -> LLMResult:
        self.image_calls.append(
            {
                "size": len(image_bytes),
                "mime": mime,
                "title": title,
                "detect": detect,
                "summarize": summarize,
            }
        )
        if self._error is not None:
            raise self._error
        return self._result


def test_candidate_from_stream_deserialization():
    c = EditCandidate.from_stream(
        {
            "rev_old": "None",
            "rev_new": "42",
            "server_name": "es.wikipedia.org",
            "wiki": "eswiki",
            "title": "Madrid",
            "user": "~2026-1-1",
            "anon": "1",
            "heur_flags": "blanking,no_comment",
        }
    )
    assert c.rev_old == 0
    assert c.rev_new == 42
    assert c.anon is True
    assert c.heur_flags == ["blanking", "no_comment"]


def test_extract_diff_text():
    html = (
        '<tr><td class="diff-deletedline"><div>Old text</div></td>'
        '<td class="diff-addedline"><div>New <ins>bold</ins> text</div></td></tr>'
        '<tr><td class="diff-context">Unchanged</td></tr>'
    )
    added, removed = extract_diff_text(html)
    assert added == "New bold text"
    assert removed == "Old text"
    assert extract_diff_text("") == ("", "")


async def test_wikimedia_client_compare_and_new_page_and_thumb():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "action=compare" in url:
            return httpx.Response(
                200,
                json={"compare": {"*": '<tr><td class="diff-addedline">Hello</td></tr>'}},
            )
        if "prop=revisions" in url:
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [
                            {"revisions": [{"slots": {"main": {"content": "Brand new article"}}}]}
                        ]
                    }
                },
            )
        if "prop=imageinfo" in url:
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": {
                            "1": {
                                "imageinfo": [
                                    {
                                        "thumburl": "https://upload.test/thumb.jpg",
                                        "thumbmime": "image/jpeg",
                                    }
                                ]
                            }
                        }
                    }
                },
            )
        return httpx.Response(200, content=b"IMGDATA", headers={"Content-Type": "image/jpeg"})

    client = WikimediaClient(
        user_agent="WikiPulse-Test/1.0",
        limiter=AsyncTokenBucket(rate_per_min=6000),
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await client.fetch_diff("en.wikipedia.org", 10, 11) == ("Hello", "")
        assert await client.fetch_diff("en.wikipedia.org", 0, 55) == ("Brand new article", "")
        assert await client.fetch_thumbnail("commons.wikimedia.org", "File:Test.jpg") == (
            b"IMGDATA",
            "image/jpeg",
        )
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    ("raw", "detect", "summarize", "expected"),
    [
        (
            '{"unsafe": true, "categories": ["hate_speech", "unknown"], '
            '"summary": "Adds slurs."}',
            True,
            True,
            LLMResult(unsafe=True, categories=["hate_speech"], summary="Adds slurs."),
        ),
        (
            '{"unsafe": true, "categories": ["S5", "invalid"]}',
            True,
            False,
            LLMResult(unsafe=False, categories=[], summary=None),
        ),
        (
            '```json\n{"summary": "Fixes a date."}\n```',
            False,
            True,
            LLMResult(unsafe=False, categories=[], summary="Fixes a date."),
        ),
        ("not-json", True, True, LLMResult()),
    ],
)
def test_parse_llm_json(raw, detect, summarize, expected):
    assert parse_llm_json(raw, detect=detect, summarize=summarize) == expected


@pytest.mark.parametrize(
    ("detect", "summarize", "expected_required"),
    [
        (True, True, {"unsafe", "categories", "summary"}),
        (True, False, {"unsafe", "categories"}),
        (False, True, {"summary"}),
    ],
)
def test_response_format_schemas_minimal(detect, summarize, expected_required):
    schema = build_response_format(detect=detect, summarize=summarize)["json_schema"]["schema"]
    assert set(schema["required"]) == expected_required


async def test_openai_analyzer_llm_single_pass_edit_and_image():
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "unsafe": True,
                                    "categories": ["hate_speech"],
                                    "summary": "Inserts hate speech.",
                                }
                            )
                        }
                    }
                ]
            },
        )

    llm = OpenAIAnalyzerLLM(
        url="http://llm.test/v1/chat/completions",
        model="gemma-4-e4b-qat",
        transport=httpx.MockTransport(handler),
    )
    try:
        res_edit = await llm.analyze_edit(
            title="Test",
            removed="old",
            added="hateful text",
            detect=True,
            summarize=True,
        )
        assert res_edit == LLMResult(
            unsafe=True, categories=["hate_speech"], summary="Inserts hate speech."
        )
        assert captured[0]["cache_prompt"] is True
        assert captured[0]["response_format"]["type"] == "json_schema"

        res_img = await llm.analyze_image(
            image_bytes=b"\x89PNG",
            mime="image/png",
            title="File:Bad.png",
            detect=True,
            summarize=True,
        )
        assert res_img.unsafe is True
        assert captured[1]["messages"][1]["content"][1]["type"] == "image_url"
    finally:
        await llm.aclose()


async def test_process_edit_single_pass_modes_and_llm_error_degradation():
    cand = EditCandidate(
        rev_old=1,
        rev_new=2,
        server_name="es.wikipedia.org",
        wiki="eswiki",
        title="Madrid",
        user="Bob",
        anon=False,
        heur_flags=["no_comment"],
    )
    fetcher = _FakeFetcher(added="New text", removed="Old text")
    llm = _FakeAnalyzerLLM(
        LLMResult(unsafe=True, categories=["vandalism"], summary="Replaces the text.")
    )

    # Detect + Summarize -> exactly ONE LLM call.
    res = await process_edit(cand, fetcher=fetcher, llm=llm, detect=True, summarize=True)
    assert len(llm.edit_calls) == 1
    assert res.flagged is True
    assert res.unsafe is True
    assert res.categories == ["vandalism"]
    assert res.heur_flags == ["no_comment"]
    assert res.summary == "Replaces the text."

    # Summarize-only -> no flagging, no heuristics, summary kept.
    llm_sum = _FakeAnalyzerLLM(LLMResult(unsafe=False, categories=[], summary="Summary only."))
    res_sum = await process_edit(cand, fetcher=fetcher, llm=llm_sum, detect=False, summarize=True)
    assert res_sum.flagged is False
    assert res_sum.heur_flags == []
    assert res_sum.summary == "Summary only."

    # LLM failure degrades gracefully while keeping zero-API heuristic flags.
    llm_err = _FakeAnalyzerLLM(error=httpx.ReadTimeout(""))
    res_err = await process_edit(cand, fetcher=fetcher, llm=llm_err, detect=True, summarize=True)
    assert res_err.unsafe is False
    assert res_err.categories == []
    assert res_err.heur_flags == ["no_comment"]
    assert res_err.flagged is True
    assert res_err.summary is None


async def test_process_image_single_pass():
    cand = ImageCandidate(
        title="File:Photo #1 (2026).jpg",
        wiki="commonswiki",
        server_name="commons.wikimedia.org",
        user="Carol",
    )
    fetcher = _FakeFetcher(image=(b"JPEG", "image/jpeg"))
    llm = _FakeAnalyzerLLM(
        LLMResult(unsafe=True, categories=["sexual_explicit"], summary="Explicit image.")
    )

    res = await process_image(cand, fetcher=fetcher, llm=llm, detect=True, summarize=True)
    assert len(llm.image_calls) == 1
    assert res.flagged is True
    assert res.categories == ["sexual_explicit"]
    assert res.summary == "Explicit image."
    assert res.link == "https://commons.wikimedia.org/wiki/File:Photo_%231_(2026).jpg"


async def test_consume_stream_loop_sliding_concurrency_reclaim_and_recovery():
    """Verify sliding window avoids head-of-line blocking, reclaims PEL, and survives blips."""
    batches: list[Any] = [
        ConnectionError("transient redis blip"),
        [("stream:cand:edits", [("2-0", {"rev_new": "2"}), ("3-0", {"rev_new": "3"})])],
        [("stream:cand:edits", [("4-0", {"rev_new": "4"})])],
    ]
    call_idx = 0
    idle_gate = asyncio.Event()

    async def fake_xreadgroup(*_args, **_kwargs):
        nonlocal call_idx
        if call_idx < len(batches):
            item = batches[call_idx]
            call_idx += 1
            if isinstance(item, Exception):
                raise item
            return item
        await idle_gate.wait()
        return []

    client = MagicMock()
    client.xautoclaim = AsyncMock(return_value=("0-0", [("1-0", {"rev_new": "1"})]))
    client.xreadgroup = AsyncMock(side_effect=fake_xreadgroup)
    client.xack = AsyncMock()

    ready_event = asyncio.Event()
    ready_event.set()
    stop_event = asyncio.Event()

    timeline: list[tuple[str, str]] = []
    finished: list[str] = []
    active = 0
    peak = 0
    slow_release = asyncio.Event()

    async def handler(fields: dict[str, str]) -> None:
        nonlocal active, peak
        rev = fields["rev_new"]
        timeline.append(("start", rev))
        active += 1
        peak = max(peak, active)
        try:
            if rev == "2":
                await asyncio.wait_for(slow_release.wait(), timeout=1.0)
                raise RuntimeError("boom")
            if rev == "4":
                slow_release.set()
            await asyncio.sleep(0)
        finally:
            active -= 1
            timeline.append(("end", rev))
            finished.append(rev)
            if len(finished) >= 4:
                stop_event.set()
                idle_gate.set()

    await asyncio.wait_for(
        consume_stream_loop(
            client,
            stream="stream:cand:edits",
            group="analyzer",
            consumer="c1",
            handler=handler,
            sem=asyncio.Semaphore(2),
            max_in_flight=2,
            is_enabled=lambda: True,
            ready_event=ready_event,
            stop_event=stop_event,
            block_ms=10,
            backoff_initial_s=0.0,
        ),
        timeout=2.0,
    )

    assert set(finished) == {"1", "2", "3", "4"}
    assert peak == 2
    assert timeline.index(("start", "4")) < timeline.index(("end", "2"))
    assert client.xack.await_count == 4


async def test_token_bucket_burst_refill_and_async_acquire(monkeypatch):
    now = 100.0
    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        nonlocal now
        slept.append(delay)
        now += delay

    monkeypatch.setattr(ratelimit_mod.asyncio, "sleep", fake_sleep)

    bucket = AsyncTokenBucket(rate_per_min=60.0, capacity=2.0, clock=lambda: now)
    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is False

    now = 100.5
    await bucket.acquire()
    assert slept == [pytest.approx(0.5)]


async def test_wikimedia_client_retries_429_503_http_date_and_maxlag(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(wikimedia_mod.asyncio, "sleep", fake_sleep)

    attempts = {"429": 0, "503": 0, "maxlag": 0}
    future_http_date = format_datetime(datetime.now(UTC) + timedelta(seconds=5), usegmt=True)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "fromrev=1&torev=2" in url:
            attempts["429"] += 1
            if attempts["429"] == 1:
                return httpx.Response(429, headers={"Retry-After": "0.25"})
            return httpx.Response(
                200,
                json={"compare": {"*": '<tr><td class="diff-addedline">Recovered429</td></tr>'}},
            )
        if "fromrev=2&torev=3" in url:
            attempts["503"] += 1
            if attempts["503"] == 1:
                return httpx.Response(503, headers={"Retry-After": future_http_date})
            return httpx.Response(
                200,
                json={"compare": {"*": '<tr><td class="diff-addedline">Recovered503</td></tr>'}},
            )
        if "fromrev=3&torev=4" in url:
            attempts["maxlag"] += 1
            if attempts["maxlag"] == 1:
                return httpx.Response(
                    200,
                    headers={"Retry-After": "not-a-number"},
                    json={"error": {"code": "maxlag", "info": "Waiting"}},
                )
            return httpx.Response(
                200,
                json={"compare": {"*": '<tr><td class="diff-addedline">AfterMaxlag</td></tr>'}},
            )
        return httpx.Response(200, text="<html>502 Bad Gateway</html>")

    client = WikimediaClient(
        user_agent="WikiPulse-Test/1.0",
        limiter=AsyncTokenBucket(rate_per_min=6000),
        transport=httpx.MockTransport(handler),
        max_retries=2,
    )
    try:
        assert await client.fetch_diff("bad/host.org", 1, 2) == ("", "")
        assert await client.fetch_diff("en.wikipedia.org", 1, 2) == ("Recovered429", "")
        assert await client.fetch_diff("en.wikipedia.org", 2, 3) == ("Recovered503", "")
        assert await client.fetch_diff("en.wikipedia.org", 3, 4) == ("AfterMaxlag", "")
        assert await client.fetch_diff("en.wikipedia.org", 5, 6) == ("", "")
    finally:
        await client.aclose()

    assert len(sleeps) == 3
    assert sleeps[0] == pytest.approx(0.25)
    assert 0.5 <= sleeps[1] <= 6.0
    assert sleeps[2] == pytest.approx(1.0)


async def test_openai_analyzer_llm_handles_malformed_envelope():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "overloaded"})

    llm = OpenAIAnalyzerLLM(
        url="http://llm.test/v1/chat/completions",
        model="gemma-4-e4b-qat",
        transport=httpx.MockTransport(handler),
    )
    try:
        res = await llm.analyze_edit(
            title="T", removed="", added="hello", detect=True, summarize=False
        )
        assert res == LLMResult()
    finally:
        await llm.aclose()


async def test_sink_writes_expected_keys_feed_and_timeseries(mock_redis):
    client, pipe = mock_redis

    cand = EditCandidate(1, 2, "en.wikipedia.org", "enwiki", "Art", "U", False, ["blanking"])
    ed = await process_edit(
        cand,
        fetcher=_FakeFetcher(added="x"),
        llm=_FakeAnalyzerLLM(LLMResult(unsafe=True, categories=["violence_harm"], summary="S.")),
        detect=True,
        summarize=True,
    )
    await write_edit_result(client, ed)

    pipe.hset.assert_called_once()
    assert pipe.hset.call_args.args[0] == edit_analysis_key(2)
    pipe.expire.assert_called_once_with(edit_analysis_key(2), 3600)
    pipe.lpush.assert_called_once()
    assert pipe.lpush.call_args.args[0] == RECENT_ANALYZED_KEY
    feed_item = json.loads(pipe.lpush.call_args.args[1])
    assert feed_item["type"] == "edit" and feed_item["flagged"] is True
    ts_keys = [call.args[1] for call in pipe.execute_command.call_args_list]
    assert ts_keys == [
        TS_EDITS_ANALYZED,
        TS_MALICIOUS_EDITS,
        hazard_ts_key("violence_harm"),
        heuristic_ts_key("blanking"),
    ]
    pipe.execute.assert_awaited_once()

    pipe.reset_mock()
    img_cand = ImageCandidate("File:X.png", "commonswiki", "commons.wikimedia.org", "U")
    im = await process_image(
        img_cand,
        fetcher=_FakeFetcher(image=(b"123", "image/png")),
        llm=_FakeAnalyzerLLM(LLMResult(unsafe=False, categories=[], summary="Photo.")),
        detect=True,
        summarize=True,
    )
    await write_image_result(client, im)

    assert pipe.hset.call_args.args[0] == image_analysis_key("File:X.png")
    img_ts_keys = [call.args[1] for call in pipe.execute_command.call_args_list]
    assert img_ts_keys == [TS_IMAGES_ANALYZED]
    pipe.execute.assert_awaited_once()


async def test_openai_llm_is_ready_probes_health_endpoint():
    status = {"code": 503}

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://llm.test:8000/health"
        if status["code"] == 0:
            raise httpx.ConnectError("refused")
        return httpx.Response(status["code"])

    llm = OpenAIAnalyzerLLM(
        url="http://llm.test:8000/v1/chat/completions",
        model="gemma-4-e4b-qat",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await llm.is_ready() is False
        status["code"] = 0
        assert await llm.is_ready() is False
        status["code"] = 200
        assert await llm.is_ready() is True
    finally:
        await llm.aclose()


async def test_monitor_llm_readiness_gates_and_recovers():
    """Deterministic readiness test driven by probe gates (zero timing sleeps)."""
    states = iter([False, True, False])
    step_done = asyncio.Event()
    next_step = asyncio.Event()

    class _SteppedLLM(_FakeAnalyzerLLM):
        async def is_ready(self) -> bool:
            await next_step.wait()
            next_step.clear()
            val = next(states, False)
            step_done.set()
            return val

    ready_event = asyncio.Event()
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        monitor_llm_readiness(
            _SteppedLLM(), ready_event, stop_event, poll_unready_s=0.0, poll_ready_s=0.0
        )
    )
    try:
        for expected in (False, True, False):
            step_done.clear()
            next_step.set()
            await asyncio.wait_for(step_done.wait(), timeout=1.0)
            await asyncio.sleep(0)
            assert ready_event.is_set() is expected
    finally:
        stop_event.set()
        next_step.set()
        await asyncio.wait_for(task, timeout=1.0)


async def test_analyzer_service_handles_edit_and_image_with_injected_deps(mock_redis):
    redis_client, pipe = mock_redis

    fetcher = _FakeFetcher(added="Vandalism text", image=(b"PNG", "image/png"))
    llm = _FakeAnalyzerLLM(LLMResult(unsafe=True, categories=["vandalism"], summary="Summary."))
    cfg = AnalyzerConfig(
        redis=RedisConfig(),
        toggles=DetectionToggles(detect_edits=True, detect_images=True, summarize=True),
    )
    svc = AnalyzerService(cfg, redis_client=redis_client, fetcher=fetcher, llm=llm)

    await svc.handle_edit(
        {
            "rev_old": "1",
            "rev_new": "2",
            "server_name": "es.wikipedia.org",
            "wiki": "eswiki",
            "title": "Prueba",
            "user": "Bob",
            "anon": "0",
            "heur_flags": "",
        }
    )
    await svc.handle_image(
        {
            "title": "File:Pic.png",
            "wiki": "commonswiki",
            "server_name": "commons.wikimedia.org",
            "user": "Bob",
        }
    )

    assert len(llm.edit_calls) == 1
    assert len(llm.image_calls) == 1
    assert pipe.execute.await_count == 2


def test_edit_prompt_truncates_large_diffs_and_format_exc_handles_empty_timeout():
    prompt = build_edit_user_prompt(
        title="BigPage",
        removed="r" * (MAX_REMOVED_CHARS + 500),
        added="a" * (MAX_ADDED_CHARS + 500),
        detect=True,
        summarize=True,
    )
    assert "r" * MAX_REMOVED_CHARS + "…" in prompt
    assert "a" * MAX_ADDED_CHARS + "…" in prompt
    assert "one English sentence" in prompt
    assert _format_exc(httpx.ReadTimeout("")) == "ReadTimeout"
    assert _format_exc(ValueError("bad")) == "ValueError: bad"

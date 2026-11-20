"""Latency benchmark for the Gemma 4 E4B QAT moderation and summarization endpoint.

Run: LLM_URL=http://localhost:8080/v1/chat/completions uv run python -m bench.bench_llm
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time

from wikipulse.analyzer.llm import OpenAIAnalyzerLLM
from wikipulse.core.config import DEFAULT_LLM_MODEL, DEFAULT_LLM_URL

SAMPLE_EDITS = [
    ("World War II", "The battle began in 1941.", "The battle began in June 1941."),
    ("Python", "", "Added section on asyncio TaskGroup introduced in Python 3.11."),
    ("Madrid", "Capital de España.", "Capital de España con más de 3 millones de habitantes."),
    ("Test page", "Hello", "You are all worthless idiots, go kill yourselves right now."),
]


async def measure(url: str, model: str, *, detect: bool, summarize: bool) -> list[float]:
    llm = OpenAIAnalyzerLLM(url=url, model=model)
    timings: list[float] = []
    try:
        # Warm up KV prefix cache with the first edit.
        title, rem, add = SAMPLE_EDITS[0]
        await llm.analyze_edit(
            title=title, removed=rem, added=add, detect=detect, summarize=summarize
        )
        for title, rem, add in SAMPLE_EDITS:
            t0 = time.perf_counter()
            await llm.analyze_edit(
                title=title, removed=rem, added=add, detect=detect, summarize=summarize
            )
            timings.append(time.perf_counter() - t0)
    finally:
        await llm.aclose()
    return timings


async def _main() -> None:
    url = os.environ.get("LLM_URL", DEFAULT_LLM_URL)
    model = os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL)
    for label, det, summ in (
        ("detect only", True, False),
        ("summarize only", False, True),
        ("detect + summarize (single-pass)", True, True),
    ):
        ts = await measure(url, model, detect=det, summarize=summ)
        p50 = statistics.median(ts) * 1000
        print(f"{label:35s} p50={p50:7.1f} ms  throughput={1000 / p50:5.1f} req/s")


if __name__ == "__main__":
    asyncio.run(_main())

"""Benchmark the in-memory sliding-window ingestor (parse + windowing + heuristics).

Run: uv run python -m bench.bench_ingestor
"""

from __future__ import annotations

import json
import statistics
import time

from wikipulse.core.config import DetectionToggles
from wikipulse.ingestor.events import parse_event, select_edit_candidate
from wikipulse.ingestor.windows import SlidingWindowAggregator


def _synthetic_sample(n: int = 5000) -> list[str]:
    base_ts = 1_760_000_000
    wikis = ("enwiki", "eswiki", "frwiki", "dewiki", "jawiki", "wikidatawiki")
    lines: list[str] = []
    for i in range(n):
        wiki = wikis[i % len(wikis)]
        payload = {
            "type": "edit",
            "namespace": 0,
            "wiki": wiki,
            "server_name": f"{wiki.removesuffix('wiki')}.wikipedia.org",
            "title": f"Article_{i % 250}",
            "user": f"~2026-{i % 100}-1" if i % 4 == 0 else f"Editor_{i % 50}",
            "bot": i % 5 == 0,
            "comment": "" if i % 7 == 0 else "Copyedit",
            "length": {"old": 2500, "new": 400 if i % 11 == 0 else 2600},
            "revision": {"old": i + 10, "new": i + 11},
            "timestamp": base_ts + (i // 30),
        }
        lines.append(json.dumps(payload))
    return lines


def bench_ingestor(n: int = 5000, runs: int = 5) -> dict[str, float]:
    sample = _synthetic_sample(n)
    toggles = DetectionToggles()
    durations: list[float] = []

    for _ in range(runs):
        agg = SlidingWindowAggregator()
        t0 = time.perf_counter()
        for raw in sample:
            ev = parse_event(raw)
            if ev is not None:
                agg.record(ev)
                select_edit_candidate(ev, toggles)
        agg.snapshots(1_760_000_200)
        durations.append(time.perf_counter() - t0)

    median_s = statistics.median(durations)
    return {
        "events": float(n),
        "median_s": median_s,
        "events_per_sec": n / median_s,
        "us_per_event": (median_s / n) * 1e6,
    }


def main() -> None:
    res = bench_ingestor()
    print(
        f"Ingestor (parse + 3 sliding windows + heuristics): "
        f"{res['events_per_sec']:,.0f} events/s ({res['us_per_event']:.1f} µs/event)"
    )


if __name__ == "__main__":
    main()

"""Single source of truth for Redis keys, streams, windows, and retention constants."""

from __future__ import annotations

from typing import Any

ALLOWED_WINDOWS: tuple[str, ...] = ("1m", "5m", "15m")
WINDOW_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
}

# Retention & sizing
TS_RETENTION_MS = 86_400_000  # 24 hours
ANALYSIS_TTL_S = 3600         # 1 hour
RECENT_FEED_MAX = 200
PULSE_MINUTES = 30
DEFAULT_STREAM_MAXLEN = 200

# Shared live configuration hash
CONFIG_HASH_KEY = "config:detection"

# Streams
EDITS_STREAM = "stream:cand:edits"
IMAGES_STREAM = "stream:cand:images"

# Meta & time-series keys
META_KEY = "metric:meta"
TS_EVENTS_PER_SEC = "ts:events_per_sec"
TS_EDITS_ANALYZED = "ts:edits_analyzed"
TS_MALICIOUS_EDITS = "ts:malicious_edits"
TS_IMAGES_ANALYZED = "ts:images_analyzed"
TS_MALICIOUS_IMAGES = "ts:malicious_images"
RECENT_ANALYZED_KEY = "recent_analyzed"

# Excluded firehose-dominating structured-data wikis (Q-IDs / file pages)
EXCLUDED_ARTICLE_WIKIS = frozenset({"wikidatawiki", "commonswiki"})


def top_articles_key(window: str) -> str:
    return f"metric:top_articles:{window}"


def lang_counts_key(window: str) -> str:
    return f"metric:lang_counts:{window}"


def bot_ratio_key(window: str) -> str:
    return f"metric:bot_ratio:{window}"


def anon_ratio_key(window: str) -> str:
    return f"metric:anon_ratio:{window}"


def edit_analysis_key(rev_id: int) -> str:
    return f"analysis:edit:{rev_id}"


def image_analysis_key(title: str) -> str:
    return f"analysis:image:{title}"


def hazard_ts_key(code: str) -> str:
    return f"ts:hazard:{code}"


def heuristic_ts_key(flag: str) -> str:
    return f"ts:hazard:heur:{flag}"


def ts_add(
    pipe: Any,
    key: str,
    value: int | float,
    *,
    on_duplicate: str,
    labels: tuple[str, ...] = (),
) -> None:
    """Append a `TS.ADD` command with shared retention settings to a Redis pipeline."""
    args: list[Any] = [
        "TS.ADD",
        key,
        "*",
        value,
        "RETENTION",
        TS_RETENTION_MS,
        "ON_DUPLICATE",
        on_duplicate,
    ]
    if labels:
        args.extend(("LABELS", *labels))
    pipe.execute_command(*args)

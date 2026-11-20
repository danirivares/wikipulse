"""Sliding event-time window aggregator for real-time Wikipedia metrics.

Maintains 1-second event-time buckets alongside incremental running counters so each
event update and bucket eviction runs in O(1) amortized time with bounded memory.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from wikipulse.core.redis_keys import WINDOW_SECONDS
from wikipulse.ingestor.events import ParsedEvent


@dataclass(slots=True)
class _SecondBucket:
    articles: Counter[str] = field(default_factory=Counter)
    wikis: Counter[str] = field(default_factory=Counter)
    bot: int = 0
    human: int = 0
    anon: int = 0
    registered: int = 0


@dataclass(frozen=True, slots=True)
class WindowSnapshot:
    label: str
    top_articles: list[tuple[str, int]]
    lang_counts: dict[str, int]
    bot: int
    human: int
    anon: int
    registered: int

    def bot_ratio_dict(self) -> dict[str, int | float]:
        total = self.bot + self.human
        ratio = round(self.bot / total, 4) if total > 0 else 0.0
        return {"bot": self.bot, "human": self.human, "ratio": ratio}

    def anon_ratio_dict(self) -> dict[str, int | float]:
        total = self.anon + self.registered
        ratio = round(self.anon / total, 4) if total > 0 else 0.0
        return {"anon": self.anon, "registered": self.registered, "ratio": ratio}


class RollingWindow:
    """Exact sliding event-time window backed by 1-second buckets and live running totals."""

    def __init__(self, label: str, duration_s: int) -> None:
        self.label = label
        self.duration_s = duration_s
        self._buckets: dict[int, _SecondBucket] = {}
        self._articles: Counter[str] = Counter()
        self._wikis: Counter[str] = Counter()
        self._bot = 0
        self._human = 0
        self._anon = 0
        self._registered = 0
        self._high_watermark = 0

    def record(self, event: ParsedEvent) -> None:
        """Ingest a single edit/new event into its event-time bucket."""
        sec = event.event_sec
        if sec > self._high_watermark:
            self._high_watermark = sec
        if sec <= self._high_watermark - self.duration_s:
            return  # Late event outside the sliding window

        bucket = self._buckets.get(sec)
        if bucket is None:
            bucket = _SecondBucket()
            self._buckets[sec] = bucket

        if event.is_article:
            article_key = (
                f"{event.server_name}\t{event.title}" if event.server_name else event.title
            )
            bucket.articles[article_key] += 1
            self._articles[article_key] += 1

        if event.wiki:
            bucket.wikis[event.wiki] += 1
            self._wikis[event.wiki] += 1

        if event.bot:
            bucket.bot += 1
            self._bot += 1
        else:
            bucket.human += 1
            self._human += 1

        if event.is_anon:
            bucket.anon += 1
            self._anon += 1
        else:
            bucket.registered += 1
            self._registered += 1

    def evict(self, now_sec: int) -> None:
        """Drop all buckets older than `[ref - duration_s + 1, ref]`."""
        ref = max(now_sec, self._high_watermark)
        cutoff = ref - self.duration_s
        expired = [sec for sec in self._buckets if sec <= cutoff]
        for sec in expired:
            bucket = self._buckets.pop(sec)
            self._subtract_counter(self._articles, bucket.articles)
            self._subtract_counter(self._wikis, bucket.wikis)
            self._bot -= bucket.bot
            self._human -= bucket.human
            self._anon -= bucket.anon
            self._registered -= bucket.registered

    @staticmethod
    def _subtract_counter(target: Counter[str], delta: Counter[str]) -> None:
        for key, count in delta.items():
            remaining = target[key] - count
            if remaining > 0:
                target[key] = remaining
            else:
                target.pop(key, None)

    def snapshot(
        self,
        now_sec: int,
        *,
        top_articles_n: int = 50,
        top_langs_n: int = 10,
    ) -> WindowSnapshot:
        """Evict expired buckets and return current top-N metrics."""
        self.evict(now_sec)
        return WindowSnapshot(
            label=self.label,
            top_articles=self._articles.most_common(top_articles_n),
            lang_counts=dict(self._wikis.most_common(top_langs_n)),
            bot=self._bot,
            human=self._human,
            anon=self._anon,
            registered=self._registered,
        )

    @property
    def active_buckets(self) -> int:
        return len(self._buckets)


class SlidingWindowAggregator:
    """Manages all configured sliding windows (1m, 5m, 15m) over edit/new events."""

    def __init__(self, windows: dict[str, int] | None = None) -> None:
        specs = WINDOW_SECONDS if windows is None else windows
        self._windows = [RollingWindow(label, dur) for label, dur in specs.items()]

    def record(self, event: ParsedEvent) -> bool:
        """Record an event if it is an edit/new event. Returns True when counted."""
        if not event.is_edit:
            return False
        for window in self._windows:
            window.record(event)
        return True

    def snapshots(self, now_sec: int) -> list[WindowSnapshot]:
        return [w.snapshot(now_sec) for w in self._windows]

"""Parsing Wikipedia EventStreams payloads and selecting moderation candidates."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from wikipulse.core.config import DetectionToggles
from wikipulse.core.heuristics import edit_heuristics, is_anon_user
from wikipulse.core.redis_keys import EXCLUDED_ARTICLE_WIKIS

IMAGE_EXTENSIONS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def is_image_title(title: str) -> bool:
    """Return True when a Wikimedia upload title ends with a raster image extension."""
    return title.lower().endswith(IMAGE_EXTENSIONS)


@dataclass(frozen=True, slots=True)
class ParsedEvent:
    kind: str
    log_type: str | None
    namespace: int | None
    wiki: str
    title: str
    server_name: str
    user: str
    bot: bool
    comment: str
    length_old: int | None
    length_new: int | None
    rev_old: int | None
    rev_new: int | None
    event_sec: int
    is_anon: bool = False

    @property
    def is_edit(self) -> bool:
        return self.kind in ("edit", "new")

    @property
    def is_upload(self) -> bool:
        return self.kind == "log" and self.log_type == "upload"

    @property
    def is_article(self) -> bool:
        return (
            bool(self.title)
            and self.namespace == 0
            and self.wiki not in EXCLUDED_ARTICLE_WIKIS
        )


def _parse_event_sec(payload: dict[str, Any], fallback_sec: int) -> int:
    meta = payload.get("meta")
    if isinstance(meta, dict):
        dt_str = meta.get("dt")
        if isinstance(dt_str, str) and dt_str:
            try:
                return int(datetime.fromisoformat(dt_str.replace("Z", "+00:00")).timestamp())
            except ValueError:
                pass
    ts = payload.get("timestamp")
    if isinstance(ts, (int, float)):
        return int(ts)
    return fallback_sec


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_event(raw: str, *, now_sec: int | None = None) -> ParsedEvent | None:
    """Parse a raw Wikimedia EventStreams JSON line. Returns None for malformed JSON."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    kind = str(data.get("type") or "")
    if not kind:
        return None

    length = data.get("length") if isinstance(data.get("length"), dict) else {}
    revision = data.get("revision") if isinstance(data.get("revision"), dict) else {}
    fallback = int(time.time()) if now_sec is None else now_sec
    user = str(data.get("user") or "")

    return ParsedEvent(
        kind=kind,
        log_type=str(data["log_type"]) if data.get("log_type") is not None else None,
        namespace=_opt_int(data.get("namespace")),
        wiki=str(data.get("wiki") or ""),
        title=str(data.get("title") or ""),
        server_name=str(data.get("server_name") or ""),
        user=user,
        bot=bool(data.get("bot", False)),
        comment=str(data.get("comment") or ""),
        length_old=_opt_int(length.get("old")),
        length_new=_opt_int(length.get("new")),
        rev_old=_opt_int(revision.get("old")),
        rev_new=_opt_int(revision.get("new")),
        event_sec=_parse_event_sec(data, fallback),
        is_anon=is_anon_user(user),
    )


def _passes_common_filters(
    event: ParsedEvent,
    toggles: DetectionToggles,
    sample_rate: float,
    rng: random.Random | None,
) -> bool:
    if toggles.exclude_bots and event.bot:
        return False
    if toggles.only_anon_new and not event.is_anon:
        return False
    if sample_rate < 1.0:
        draw = rng.random() if rng is not None else random.random()
        if draw >= max(sample_rate, 0.0):
            return False
    return True


def select_edit_candidate(
    event: ParsedEvent,
    toggles: DetectionToggles,
    *,
    sample_rate: float = 1.0,
    rng: random.Random | None = None,
) -> dict[str, str] | None:
    """Build a Redis Stream entry for an article edit, or None if filtered out."""
    if not (toggles.detect_edits or toggles.summarize):
        return None
    if not (event.is_edit and event.is_article):
        return None
    if not _passes_common_filters(event, toggles, sample_rate, rng):
        return None

    flags = edit_heuristics(event.length_old, event.length_new, event.comment)
    return {
        "rev_old": "" if event.rev_old is None else str(event.rev_old),
        "rev_new": "" if event.rev_new is None else str(event.rev_new),
        "server_name": event.server_name,
        "wiki": event.wiki,
        "title": event.title,
        "user": event.user,
        "anon": "1" if event.is_anon else "0",
        "heur_flags": ",".join(flags),
    }


def select_image_candidate(
    event: ParsedEvent,
    toggles: DetectionToggles,
    *,
    sample_rate: float = 1.0,
    rng: random.Random | None = None,
) -> dict[str, str] | None:
    """Build a Redis Stream entry for an uploaded image, or None if filtered out."""
    if not (toggles.detect_images or toggles.summarize):
        return None
    if not (event.is_upload and is_image_title(event.title)):
        return None
    if not _passes_common_filters(event, toggles, sample_rate, rng):
        return None

    return {
        "title": event.title,
        "wiki": event.wiki,
        "server_name": event.server_name,
        "user": event.user,
    }

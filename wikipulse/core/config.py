"""Typed configuration and shared live feature toggles."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from wikipulse.core.redis_keys import (
    CONFIG_HASH_KEY,
    DEFAULT_STREAM_MAXLEN,
    EDITS_STREAM,
    IMAGES_STREAM,
)

DEFAULT_WIKIMEDIA_URL = "https://stream.wikimedia.org/v2/stream/recentchange"
DEFAULT_USER_AGENT = "WikiPulse/1.0 (contact@example.com)"
DEFAULT_LLM_URL = "http://localhost:8080/v1/chat/completions"
DEFAULT_LLM_MODEL = "gemma-4-e4b-qat"


def as_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True, slots=True)
class DetectionToggles:
    """Live runtime toggles stored in Redis `config:detection` and shared across services."""

    detect_edits: bool = True
    detect_images: bool = False
    summarize: bool = False
    exclude_bots: bool = True
    only_anon_new: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> DetectionToggles:
        src = os.environ if env is None else env
        return cls(
            detect_edits=as_bool(src.get("DETECT_EDITS"), True),
            detect_images=as_bool(src.get("DETECT_IMAGES"), False),
            summarize=as_bool(src.get("SUMMARIZE"), False),
            exclude_bots=as_bool(src.get("DETECT_EXCLUDE_BOTS"), True),
            only_anon_new=as_bool(src.get("DETECT_ONLY_ANON"), False),
        )

    @classmethod
    def from_redis_hash(
        cls,
        raw: Mapping[str, str],
        base: DetectionToggles | None = None,
    ) -> DetectionToggles:
        defaults = base or cls()
        return cls(
            detect_edits=as_bool(raw.get("detect_edits"), defaults.detect_edits),
            detect_images=as_bool(raw.get("detect_images"), defaults.detect_images),
            summarize=as_bool(raw.get("summarize"), defaults.summarize),
            exclude_bots=as_bool(raw.get("exclude_bots"), defaults.exclude_bots),
            only_anon_new=as_bool(raw.get("only_anon_new"), defaults.only_anon_new),
        )

    def to_redis_hash(self) -> dict[str, str]:
        return {k: ("true" if v else "false") for k, v in self.to_dict().items()}

    def to_dict(self) -> dict[str, bool]:
        return {
            "detect_edits": self.detect_edits,
            "detect_images": self.detect_images,
            "summarize": self.summarize,
            "exclude_bots": self.exclude_bots,
            "only_anon_new": self.only_anon_new,
        }

    def with_patch(self, patch: Mapping[str, bool | None]) -> DetectionToggles:
        updates = {k: v for k, v in patch.items() if v is not None}
        return replace(self, **updates)


async def seed_toggles(client: Any, toggles: DetectionToggles) -> None:
    """Seed Redis `config:detection` in one pipeline without overwriting live overrides."""
    pipe = client.pipeline(transaction=False)
    for field, value in toggles.to_redis_hash().items():
        pipe.hsetnx(CONFIG_HASH_KEY, field, value)
    await pipe.execute()


@dataclass(frozen=True, slots=True)
class RedisConfig:
    host: str = "localhost"
    port: int = 6379

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RedisConfig:
        src = os.environ if env is None else env
        return cls(
            host=src.get("REDIS_HOST", "localhost"),
            port=int(src.get("REDIS_PORT", "6379")),
        )


@dataclass(frozen=True, slots=True)
class IngestorConfig:
    redis: RedisConfig
    toggles: DetectionToggles
    wikimedia_url: str = DEFAULT_WIKIMEDIA_URL
    user_agent: str = DEFAULT_USER_AGENT
    sample_rate: float = 1.0
    stream_maxlen: int = DEFAULT_STREAM_MAXLEN
    flush_interval_s: float = 1.0
    edits_stream: str = EDITS_STREAM
    images_stream: str = IMAGES_STREAM
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> IngestorConfig:
        src = os.environ if env is None else env
        return cls(
            redis=RedisConfig.from_env(src),
            toggles=DetectionToggles.from_env(src),
            wikimedia_url=src.get("WIKIMEDIA_URL", DEFAULT_WIKIMEDIA_URL),
            user_agent=src.get("USER_AGENT", DEFAULT_USER_AGENT),
            sample_rate=float(src.get("SAMPLE_RATE", "1.0")),
            stream_maxlen=int(src.get("STREAM_MAXLEN", str(DEFAULT_STREAM_MAXLEN))),
            flush_interval_s=float(src.get("FLUSH_INTERVAL_S", "1.0")),
            edits_stream=src.get("EDITS_STREAM", EDITS_STREAM),
            images_stream=src.get("IMAGES_STREAM", IMAGES_STREAM),
            log_level=src.get("LOG_LEVEL", "INFO"),
        )


@dataclass(frozen=True, slots=True)
class AnalyzerConfig:
    redis: RedisConfig
    toggles: DetectionToggles
    user_agent: str = DEFAULT_USER_AGENT
    max_fetches_per_min: int = 180
    max_concurrency: int = 4
    llm_url: str = DEFAULT_LLM_URL
    llm_model: str = DEFAULT_LLM_MODEL
    llm_timeout_s: float = 45.0
    edits_stream: str = EDITS_STREAM
    images_stream: str = IMAGES_STREAM
    consumer_group: str = "analyzer"
    image_consumer_group: str = "analyzer-images"
    consumer_name: str = "analyzer-1"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AnalyzerConfig:
        src = os.environ if env is None else env
        return cls(
            redis=RedisConfig.from_env(src),
            toggles=DetectionToggles.from_env(src),
            user_agent=src.get("USER_AGENT", DEFAULT_USER_AGENT),
            max_fetches_per_min=int(src.get("MAX_FETCHES_PER_MIN", "180")),
            max_concurrency=max(1, int(src.get("ANALYZER_CONCURRENCY", "4"))),
            llm_url=src.get("LLM_URL", DEFAULT_LLM_URL),
            llm_model=src.get("LLM_MODEL", DEFAULT_LLM_MODEL),
            llm_timeout_s=float(src.get("LLM_TIMEOUT_S", "45.0")),
            edits_stream=src.get("EDITS_STREAM", EDITS_STREAM),
            images_stream=src.get("IMAGES_STREAM", IMAGES_STREAM),
            consumer_group=src.get("CONSUMER_GROUP", "analyzer"),
            image_consumer_group=src.get("IMAGE_CONSUMER_GROUP", "analyzer-images"),
            consumer_name=src.get("CONSUMER_NAME", "analyzer-1"),
            log_level=src.get("LOG_LEVEL", "INFO"),
        )


@dataclass(frozen=True, slots=True)
class ApiConfig:
    redis: RedisConfig
    host: str = "0.0.0.0"
    port: int = 8000
    sse_interval_s: float = 1.0
    cache_ttl_s: float = 0.8
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ApiConfig:
        src = os.environ if env is None else env
        return cls(
            redis=RedisConfig.from_env(src),
            host=src.get("API_HOST", "0.0.0.0"),
            port=int(src.get("API_PORT", "8000")),
            sse_interval_s=float(src.get("SSE_INTERVAL_S", "1.0")),
            cache_ttl_s=float(src.get("CACHE_TTL_S", "0.8")),
            log_level=src.get("LOG_LEVEL", "INFO"),
        )

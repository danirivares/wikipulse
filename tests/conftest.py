"""Shared pytest fixtures for WikiPulse unit tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def make_mock_redis(
    *,
    execute_return: Any = None,
    execute_side_effect: Any = None,
) -> tuple[MagicMock, MagicMock]:
    """Return a `(client, pipe)` pair mimicking `redis.asyncio.Redis.pipeline()`."""
    pipe = MagicMock()
    if execute_side_effect is not None:
        pipe.execute = AsyncMock(side_effect=execute_side_effect)
    else:
        pipe.execute = AsyncMock(return_value=[] if execute_return is None else execute_return)
    client = MagicMock()
    client.pipeline.return_value = pipe
    return client, pipe


@pytest.fixture
def mock_redis() -> tuple[MagicMock, MagicMock]:
    """Fresh `(redis_client, pipeline)` mock pair for each test."""
    return make_mock_redis()

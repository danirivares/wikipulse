"""Tests for wikipulse.core: config toggles, heuristics, hazard taxonomy, and wiki URLs."""

from __future__ import annotations

import pytest

from wikipulse.core.config import (
    AnalyzerConfig,
    DetectionToggles,
    IngestorConfig,
    as_bool,
    seed_toggles,
)
from wikipulse.core.hazards import ACTIVE_HAZARD_CODES, filter_categories
from wikipulse.core.heuristics import edit_heuristics, is_anon_user
from wikipulse.core.redis_keys import CONFIG_HASH_KEY
from wikipulse.core.wiki import build_diff_url, build_wiki_url, is_valid_server_name


@pytest.mark.parametrize(
    ("raw", "default", "expected"),
    [
        ("true", False, True),
        ("1", False, True),
        ("ON", False, True),
        ("yes", False, True),
        ("false", True, False),
        ("0", True, False),
        (None, True, True),
        (None, False, False),
        (True, False, True),
        (False, True, False),
    ],
)
def test_as_bool(raw, default, expected):
    assert as_bool(raw, default=default) is expected


def test_detection_toggles_env_and_redis_override():
    base = DetectionToggles.from_env(
        {
            "DETECT_EDITS": "true",
            "DETECT_IMAGES": "false",
            "SUMMARIZE": "false",
            "DETECT_EXCLUDE_BOTS": "true",
            "DETECT_ONLY_ANON": "false",
        }
    )
    assert base.detect_edits is True
    assert base.summarize is False

    live = DetectionToggles.from_redis_hash(
        {"summarize": "true", "detect_images": "1", "only_anon_new": "yes"},
        base=base,
    )
    assert live == DetectionToggles(
        detect_edits=True,
        detect_images=True,
        summarize=True,
        exclude_bots=True,
        only_anon_new=True,
    )


async def test_seed_toggles_uses_pipelined_hsetnx(mock_redis):
    client, pipe = mock_redis
    toggles = DetectionToggles(detect_edits=True, summarize=True)

    await seed_toggles(client, toggles)

    assert pipe.hsetnx.call_count == 5
    pipe.hsetnx.assert_any_call(CONFIG_HASH_KEY, "detect_edits", "true")
    pipe.hsetnx.assert_any_call(CONFIG_HASH_KEY, "summarize", "true")
    pipe.execute.assert_awaited_once()


def test_service_configs_from_env():
    ing = IngestorConfig.from_env({"REDIS_PORT": "6380", "SAMPLE_RATE": "0.5"})
    assert ing.redis.port == 6380
    assert ing.sample_rate == 0.5

    ana = AnalyzerConfig.from_env({"ANALYZER_CONCURRENCY": "8", "LLM_MODEL": "custom-gemma"})
    assert ana.max_concurrency == 8
    assert ana.llm_model == "custom-gemma"


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ("~2026-12345-1", True),
        ("~2025-1-99", True),
        ("Alice", False),
        ("", False),
        (None, False),
    ],
)
def test_is_anon_user(user, expected):
    assert is_anon_user(user) is expected


@pytest.mark.parametrize(
    ("old_len", "new_len", "comment", "expected"),
    [
        (1000, 200, "cleared", ["blanking"]),
        (5000, 2500, "trim", ["mass_delete"]),
        (1000, 1050, "   ", ["no_comment"]),
        (1000, 100, "", ["blanking", "no_comment"]),
        (1000, 1050, "Fixed typo", []),
        (None, 500, "New page", []),
    ],
)
def test_edit_heuristics(old_len, new_len, comment, expected):
    assert edit_heuristics(old_len, new_len, comment) == expected


def test_filter_categories_normalizes_and_drops_unknown_codes():
    assert "vandalism" in ACTIVE_HAZARD_CODES
    assert "hate_speech" in ACTIVE_HAZARD_CODES
    assert filter_categories(["HATE_SPEECH", "S5", "vandalism", "hate_speech", "UNKNOWN"]) == [
        "hate_speech",
        "vandalism",
    ]


@pytest.mark.parametrize(
    ("host", "valid"),
    [
        ("en.wikipedia.org", True),
        ("commons.wikimedia.org", True),
        ("bad/host.org", False),
        ("evil.org@en.wikipedia.org", False),
        ("a..b.org", False),
        ("bad host", False),
        ("", False),
    ],
)
def test_is_valid_server_name(host, valid):
    assert is_valid_server_name(host) is valid


def test_wiki_url_builders_encode_titles_and_reject_invalid_inputs():
    assert (
        build_wiki_url("commons.wikimedia.org", "File:Photo #1 (2026)?.jpg")
        == "https://commons.wikimedia.org/wiki/File:Photo_%231_(2026)%3F.jpg"
    )
    assert build_wiki_url("bad/host", "Python") == ""
    assert build_diff_url("es.wikipedia.org", 42) == "https://es.wikipedia.org/w/index.php?diff=42"
    assert build_diff_url("es.wikipedia.org", 0) == ""
    assert build_diff_url("bad host", 42) == ""

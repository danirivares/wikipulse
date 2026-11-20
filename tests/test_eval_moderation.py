"""Tests for bench.eval_moderation."""

from __future__ import annotations

from bench.eval_moderation import score


def test_eval_moderation_score():
    rows = [
        {"label": "malicious", "categories": ["hate_speech"]},
        {"label": "benign", "categories": ["S5"]},
        {"label": "benign", "categories": ["unknown"]},
        {"label": "benign", "categories": ["vandalism"]},
    ]
    res = score(rows)
    assert res["baseline"] == {"flagged": 4, "precision": 0.25}
    assert res["filtered"] == {"flagged": 2, "precision": 0.5, "malicious_dropped": 0}

"""Per-candidate async orchestration: fetch -> single-pass Gemma 4 E4B QAT -> result."""

from __future__ import annotations

import logging

from wikipulse.analyzer.llm import AnalyzerLLM
from wikipulse.analyzer.models import (
    EditAnalysis,
    EditCandidate,
    ImageAnalysis,
    ImageCandidate,
    LLMResult,
)
from wikipulse.analyzer.wikimedia import Fetcher
from wikipulse.core.wiki import build_diff_url, build_wiki_url

log = logging.getLogger("wikipulse.analyzer.pipeline")


def _format_exc(exc: Exception) -> str:
    msg = str(exc).strip()
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


async def process_edit(
    candidate: EditCandidate,
    *,
    fetcher: Fetcher,
    llm: AnalyzerLLM,
    detect: bool,
    summarize: bool,
) -> EditAnalysis:
    """Fetch edit diff and evaluate moderation + English summary in a single LLM pass."""
    added, removed = await fetcher.fetch_diff(
        candidate.server_name, candidate.rev_old, candidate.rev_new
    )

    # Classification only inspects edits with added text; summarization uses added or removed.
    should_detect = detect and bool(added)
    should_summarize = summarize and bool(added or removed)

    llm_result = LLMResult()
    if should_detect or should_summarize:
        try:
            llm_result = await llm.analyze_edit(
                title=candidate.title,
                removed=removed,
                added=added,
                detect=should_detect,
                summarize=should_summarize,
            )
        except Exception as exc:  # noqa: BLE001 — degrade gracefully, never drop candidate
            log.warning(
                "LLM edit analysis failed for rev %s: %s",
                candidate.rev_new,
                _format_exc(exc),
            )

    if detect:
        unsafe = llm_result.unsafe
        categories = llm_result.categories if unsafe else []
        heur_flags = list(candidate.heur_flags)
        flagged = unsafe or bool(heur_flags)
    else:
        unsafe = False
        categories = []
        heur_flags = []
        flagged = False

    return EditAnalysis(
        rev_id=candidate.rev_new,
        title=candidate.title,
        wiki=candidate.wiki,
        user=candidate.user,
        flagged=flagged,
        unsafe=unsafe,
        categories=categories,
        heur_flags=heur_flags,
        summary=llm_result.summary if summarize else None,
        link=build_diff_url(candidate.server_name, candidate.rev_new),
    )


async def process_image(
    candidate: ImageCandidate,
    *,
    fetcher: Fetcher,
    llm: AnalyzerLLM,
    detect: bool,
    summarize: bool,
) -> ImageAnalysis:
    """Fetch uploaded thumbnail and evaluate moderation + English description in one pass."""
    data, mime = await fetcher.fetch_thumbnail(candidate.server_name, candidate.title, width=384)

    llm_result = LLMResult()
    if data and (detect or summarize):
        try:
            llm_result = await llm.analyze_image(
                image_bytes=data,
                mime=mime,
                title=candidate.title,
                detect=detect,
                summarize=summarize,
            )
        except Exception as exc:  # noqa: BLE001 — degrade gracefully
            log.warning(
                "LLM image analysis failed for %s: %s",
                candidate.title,
                _format_exc(exc),
            )

    unsafe = bool(detect and llm_result.unsafe and llm_result.categories)
    categories = llm_result.categories if unsafe else []

    return ImageAnalysis(
        title=candidate.title,
        wiki=candidate.wiki,
        user=candidate.user,
        flagged=unsafe,
        unsafe=unsafe,
        categories=categories,
        summary=llm_result.summary if summarize else None,
        link=build_wiki_url(candidate.server_name, candidate.title),
    )

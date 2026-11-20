"""OpenAI-compatible multimodal client for Gemma 4 E4B QAT via llama-server."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from wikipulse.analyzer.models import LLMResult
from wikipulse.analyzer.prompts import (
    EDIT_SYSTEM_PROMPT,
    IMAGE_SYSTEM_PROMPT,
    build_edit_user_prompt,
    build_image_user_prompt,
    build_response_format,
    max_tokens_for,
)
from wikipulse.core.hazards import filter_categories

log = logging.getLogger("wikipulse.analyzer.llm")


class AnalyzerLLM(Protocol):
    async def is_ready(self) -> bool: ...

    async def analyze_edit(
        self,
        *,
        title: str,
        removed: str,
        added: str,
        detect: bool,
        summarize: bool,
    ) -> LLMResult: ...

    async def analyze_image(
        self,
        *,
        image_bytes: bytes,
        mime: str,
        title: str,
        detect: bool,
        summarize: bool,
    ) -> LLMResult: ...


def _strip_code_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_llm_json(raw: str, *, detect: bool, summarize: bool) -> LLMResult:
    """Parse structured JSON response with defense-in-depth taxonomy filtering."""
    cleaned = _strip_code_fences(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("LLM returned non-JSON output: %r", raw[:120])
        return LLMResult()

    if not isinstance(data, dict):
        log.warning("LLM returned non-object JSON: %r", raw[:120])
        return LLMResult()

    unsafe = False
    categories: list[str] = []
    if detect:
        raw_unsafe = bool(data.get("unsafe", False))
        raw_cats = data.get("categories")
        if raw_unsafe and isinstance(raw_cats, list):
            categories = filter_categories(str(c) for c in raw_cats)
            unsafe = bool(categories)

    summary: str | None = None
    if summarize:
        raw_summary = data.get("summary")
        if isinstance(raw_summary, str) and raw_summary.strip():
            summary = raw_summary.strip()

    return LLMResult(unsafe=unsafe, categories=categories, summary=summary)


class OpenAIAnalyzerLLM:
    """Single pooled client targeting `llama-server` (or any OpenAI-compatible runtime)."""

    def __init__(
        self,
        *,
        url: str,
        model: str,
        timeout_s: float = 45.0,
        max_connections: int = 16,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url
        parts = urlsplit(url)
        self._health_url = f"{parts.scheme}://{parts.netloc}/health"
        self._model = model
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(timeout_s),
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_connections,
            ),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def is_ready(self) -> bool:
        """Return True when the LLM server's /health probe responds 200 OK."""
        try:
            resp = await self._client.get(self._health_url, timeout=2.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def _complete(
        self,
        *,
        messages: list[dict[str, Any]],
        detect: bool,
        summarize: bool,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": max_tokens_for(detect=detect, summarize=summarize),
            "response_format": build_response_format(detect=detect, summarize=summarize),
            # Hint llama-server to reuse the constant system-prompt KV prefix.
            "cache_prompt": True,
        }
        resp = await self._client.post(self._url, json=payload)
        resp.raise_for_status()
        try:
            body = resp.json()
            choices = body.get("choices") if isinstance(body, dict) else None
            first = choices[0] if isinstance(choices, list) and choices else None
            message = first.get("message") if isinstance(first, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
        except ValueError:
            log.warning("LLM returned invalid JSON envelope")
            return LLMResult()
        if not isinstance(content, str):
            log.warning("LLM response missing message content: %r", str(body)[:120])
            return LLMResult()
        return parse_llm_json(content, detect=detect, summarize=summarize)

    async def analyze_edit(
        self,
        *,
        title: str,
        removed: str,
        added: str,
        detect: bool,
        summarize: bool,
    ) -> LLMResult:
        if not (detect or summarize):
            return LLMResult()
        user_prompt = build_edit_user_prompt(
            title=title,
            removed=removed,
            added=added,
            detect=detect,
            summarize=summarize,
        )
        messages = [
            {"role": "system", "content": EDIT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        return await self._complete(messages=messages, detect=detect, summarize=summarize)

    async def analyze_image(
        self,
        *,
        image_bytes: bytes,
        mime: str,
        title: str,
        detect: bool,
        summarize: bool,
    ) -> LLMResult:
        if not (detect or summarize) or not image_bytes:
            return LLMResult()
        b64 = base64.b64encode(image_bytes).decode("ascii")
        instruction = build_image_user_prompt(title=title, detect=detect, summarize=summarize)
        messages = [
            {"role": "system", "content": IMAGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            },
        ]
        return await self._complete(messages=messages, detect=detect, summarize=summarize)

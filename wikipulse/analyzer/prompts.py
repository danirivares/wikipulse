"""Prefix-cache-friendly system prompts and strict JSON Schemas for Gemma 4 E4B QAT.

Keeping the system prompt constant across requests allows `llama-server` (`--cache-reuse`)
to reuse the prefilled KV cache on every slot, slashing per-edit prefill latency.
Using `json_schema` response format enforces GBNF grammar decoding so the model can never
emit malformed JSON or out-of-taxonomy hazard codes.
"""

from __future__ import annotations

from typing import Any

from wikipulse.core.hazards import ACTIVE_HAZARD_CODES, ACTIVE_HAZARDS

MAX_ADDED_CHARS = 1200
MAX_REMOVED_CHARS = 600

_TAXONOMY_BULLETS = "\n".join(f"- {code}: {desc}" for code, desc in ACTIVE_HAZARDS.items())

EDIT_SYSTEM_PROMPT = (
    "You are a multilingual Wikipedia content moderator and diff summarizer.\n"
    "Edits may be in ANY language — analyze them directly without translating.\n\n"
    "Encyclopedia context rule (CRITICAL):\n"
    "Wikipedia legitimately covers history, wars, crimes, biographies, medicine, weapons, "
    "anatomy, and politics. Neutral factual reporting, sourced quotes, and ordinary edits "
    "are SAFE (unsafe=false, categories=[]). Flag ONLY when the ADDED text itself introduces "
    "deliberate vandalism, spam, hate speech, personal harassment, doxxing, explicit sexual "
    "material, or threats/actionable harm.\n\n"
    f"Active hazard codes (use ONLY these when unsafe=true):\n{_TAXONOMY_BULLETS}\n\n"
    "Summary rule (when requested): write ONE concise sentence in English describing ONLY "
    "what changed (what was added, removed, or reworded), without repeating unchanged text.\n"
    "Respond strictly as JSON matching the requested schema."
)

IMAGE_SYSTEM_PROMPT = (
    "You are a multimodal Wikipedia image safety moderator and describer.\n"
    "Encyclopedia context rule: educational, historical, scientific, or anatomical images "
    "are SAFE unless they show explicit pornography, graphic abuse, CSAM, hate symbols "
    "uploaded as vandalism, commercial spam, or doxxing of private personal documents.\n\n"
    f"Active hazard codes (use ONLY these when unsafe=true):\n{_TAXONOMY_BULLETS}\n\n"
    "Summary rule (when requested): write ONE concise sentence in English describing what "
    "is actually shown in the image.\n"
    "Respond strictly as JSON matching the requested schema."
)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def build_edit_user_prompt(
    *,
    title: str,
    removed: str,
    added: str,
    detect: bool,
    summarize: bool,
) -> str:
    parts: list[str] = []
    if title:
        parts.append(f"Article: {title}")
    if removed:
        parts.append(f"Removed: {_truncate(removed, MAX_REMOVED_CHARS)}")
    if added:
        parts.append(f"Added: {_truncate(added, MAX_ADDED_CHARS)}")

    tasks: list[str] = []
    if detect:
        tasks.append("classify whether the ADDED text is unsafe")
    if summarize:
        tasks.append("summarize the change in one English sentence")
    parts.append("Task: " + " and ".join(tasks) + ".")
    return "\n".join(parts)


def build_image_user_prompt(*, title: str, detect: bool, summarize: bool) -> str:
    ctx = f'Wikipedia file "{title}".' if title else "Wikipedia uploaded image."
    tasks: list[str] = []
    if detect:
        tasks.append("classify whether the image is unsafe")
    if summarize:
        tasks.append("describe what is shown in one English sentence")
    return f"{ctx} Task: " + " and ".join(tasks) + "."


def build_response_format(*, detect: bool, summarize: bool) -> dict[str, Any]:
    """Build a minimal OpenAI `json_schema` response format for the active toggles."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    if detect:
        properties["unsafe"] = {"type": "boolean"}
        properties["categories"] = {
            "type": "array",
            "items": {"type": "string", "enum": list(ACTIVE_HAZARD_CODES)},
        }
        required.extend(["unsafe", "categories"])

    if summarize:
        properties["summary"] = {"type": "string"}
        required.append("summary")

    name = (
        "moderation_and_summary"
        if (detect and summarize)
        else ("moderation_only" if detect else "summary_only")
    )

    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def max_tokens_for(*, detect: bool, summarize: bool) -> int:
    if detect and summarize:
        return 140
    if summarize:
        return 96
    return 40

"""Domain dataclasses for analyzer candidates, LLM results, and persisted analyses."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


def _to_int(value: str | None) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True, slots=True)
class EditCandidate:
    rev_old: int
    rev_new: int
    server_name: str
    wiki: str
    title: str
    user: str
    anon: bool
    heur_flags: list[str]

    @classmethod
    def from_stream(cls, fields: Mapping[str, str]) -> EditCandidate:
        raw_flags = fields.get("heur_flags", "")
        return cls(
            rev_old=_to_int(fields.get("rev_old")),
            rev_new=_to_int(fields.get("rev_new")),
            server_name=fields.get("server_name", ""),
            wiki=fields.get("wiki", ""),
            title=fields.get("title", ""),
            user=fields.get("user", ""),
            anon=fields.get("anon", "0") == "1",
            heur_flags=[f for f in raw_flags.split(",") if f],
        )


@dataclass(frozen=True, slots=True)
class ImageCandidate:
    title: str
    wiki: str
    server_name: str
    user: str

    @classmethod
    def from_stream(cls, fields: Mapping[str, str]) -> ImageCandidate:
        return cls(
            title=fields.get("title", ""),
            wiki=fields.get("wiki", ""),
            server_name=fields.get("server_name", ""),
            user=fields.get("user", ""),
        )


@dataclass(frozen=True, slots=True)
class LLMResult:
    unsafe: bool = False
    categories: list[str] = field(default_factory=list)
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class EditAnalysis:
    rev_id: int
    title: str
    wiki: str
    user: str
    flagged: bool
    unsafe: bool
    categories: list[str]
    heur_flags: list[str]
    summary: str | None
    link: str


@dataclass(frozen=True, slots=True)
class ImageAnalysis:
    title: str
    wiki: str
    user: str
    flagged: bool
    unsafe: bool
    categories: list[str]
    summary: str | None
    link: str

"""Wikipedia-focused content hazard taxonomy for live edit and image moderation.

Uses clear semantic codes tailored to real Wikipedia abuse patterns (vandalism, spam,
hate speech, harassment, doxxing, explicit sexual content, and violence/self-harm)
rather than opaque generic safety indices, keeping encyclopedic coverage safe.
"""

from __future__ import annotations

from collections.abc import Iterable

# Active moderation categories for Wikipedia edits and uploaded images.
ACTIVE_HAZARDS: dict[str, str] = {
    "vandalism": (
        "Deliberate article defacement, gibberish/graffiti, hoax claims (such as fake "
        "deaths), profanity spam, or prank edits"
    ),
    "spam": (
        "Commercial advertising, SEO link injection, phishing URLs, crypto/financial "
        "scams, or unsolicited promotional content"
    ),
    "hate_speech": (
        "Slurs, dehumanization, or incitement to hatred or discrimination against "
        "protected groups"
    ),
    "harassment": (
        "Targeted personal attacks, threats, bullying, or malicious defamatory abuse "
        "inserted against individuals"
    ),
    "doxxing": (
        "Publishing non-public personal information such as home addresses, phone "
        "numbers, national IDs, or private credentials"
    ),
    "sexual_explicit": (
        "Explicit pornography, graphic sexual vandalism, or child exploitation (CSAM); "
        "never clinical, anatomical, or educational material"
    ),
    "violence_harm": (
        "Violent threats, incitement to violence, suicide/self-harm encouragement, or "
        "actionable instructions for weapons, explosives, or severe crimes"
    ),
}

ACTIVE_HAZARD_CODES: tuple[str, ...] = tuple(ACTIVE_HAZARDS.keys())
_ACTIVE_SET: frozenset[str] = frozenset(ACTIVE_HAZARD_CODES)


def filter_categories(categories: Iterable[str]) -> list[str]:
    """Normalize, deduplicate, and filter categories to the active Wikipedia taxonomy."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in categories:
        code = raw.strip().lower()
        if code in _ACTIVE_SET and code not in seen:
            seen.add(code)
            result.append(code)
    return result

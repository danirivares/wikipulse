"""Pure structural-vandalism heuristics over Wikipedia firehose metadata."""

from __future__ import annotations

import re

# MediaWiki temporary accounts (privacy-preserving replacement for IP-based anon edits)
ANON_USER_RE = re.compile(r"^~\d{4}-\d+-\d+$")

BLANKING_MIN_OLD_BYTES = 500
BLANKING_REMAINING_RATIO = 0.3  # new <= 30% of old -> blanking
MASS_DELETE_BYTES = 2000        # net removal >= 2000 bytes


def is_anon_user(user: str | None) -> bool:
    """Return True if the username matches a MediaWiki temporary account."""
    return bool(user) and bool(ANON_USER_RE.match(user))


def edit_heuristics(
    length_old: int | None,
    length_new: int | None,
    comment: str | None,
) -> list[str]:
    """Compute cheap, zero-API structural vandalism flags from event metadata."""
    flags: list[str] = []
    if length_old is not None and length_new is not None:
        if (
            length_old >= BLANKING_MIN_OLD_BYTES
            and length_new <= length_old * BLANKING_REMAINING_RATIO
        ):
            flags.append("blanking")
        elif (length_new - length_old) <= -MASS_DELETE_BYTES:
            flags.append("mass_delete")
    if not (comment or "").strip():
        flags.append("no_comment")
    return flags

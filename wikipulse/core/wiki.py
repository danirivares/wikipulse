"""Wikimedia hostname validation and canonical URL builders."""

from __future__ import annotations

import re
from urllib.parse import quote

_HOSTNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$", re.IGNORECASE)


def is_valid_server_name(server_name: str) -> bool:
    """Return True when `server_name` is a syntactically safe DNS hostname."""
    if not server_name or len(server_name) > 253 or ".." in server_name:
        return False
    return bool(_HOSTNAME_RE.match(server_name))


def build_wiki_url(server_name: str, title: str) -> str:
    """Build an RFC-encoded Wikimedia article/file URL, or empty string if invalid."""
    if not title or not is_valid_server_name(server_name):
        return ""
    slug = quote(title.replace(" ", "_"), safe="/:@!$&'()*+,;=")
    return f"https://{server_name}/wiki/{slug}"


def build_diff_url(server_name: str, rev_new: int) -> str:
    """Build a Wikimedia revision diff URL, or empty string if invalid."""
    if rev_new <= 0 or not is_valid_server_name(server_name):
        return ""
    return f"https://{server_name}/w/index.php?diff={rev_new}"

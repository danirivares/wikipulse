"""Rate-limited async Wikimedia Action API client for diffs and image thumbnails."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Protocol

import httpx

from wikipulse.analyzer.ratelimit import AsyncTokenBucket
from wikipulse.core.wiki import is_valid_server_name

log = logging.getLogger("wikipulse.analyzer.wikimedia")

MAXLAG_SECONDS = 5
MAX_NEW_PAGE_CHARS = 4000
_MAX_RETRY_AFTER_S = 60.0


class Fetcher(Protocol):
    async def fetch_diff(self, server_name: str, old_rev: int, new_rev: int) -> tuple[str, str]: ...
    async def fetch_thumbnail(
        self, server_name: str, file_title: str, width: int = 512
    ) -> tuple[bytes, str]: ...


class _DiffTextParser(HTMLParser):
    """Extract added and removed text cells from Wikimedia's compare-API diff HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._mode: str | None = None
        self.added: list[str] = []
        self.removed: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "td":
            classes = dict(attrs).get("class") or ""
            if "diff-addedline" in classes:
                self._mode = "added"
            elif "diff-deletedline" in classes:
                self._mode = "removed"
            else:
                self._mode = None

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self._mode = None

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._mode == "added":
            self.added.append(text)
        elif self._mode == "removed":
            self.removed.append(text)


def extract_diff_text(diff_html: str) -> tuple[str, str]:
    """Return `(added_text, removed_text)` from Wikimedia compare-API HTML."""
    if not diff_html:
        return "", ""
    parser = _DiffTextParser()
    parser.feed(diff_html)
    return " ".join(parser.added), " ".join(parser.removed)


def _parse_retry_after(header: str | None, default: float = 1.0) -> float:
    """Parse numeric or RFC 9110 HTTP-date `Retry-After` headers safely."""
    if not header:
        return default
    raw = header.strip()
    try:
        return max(0.05, min(float(raw), _MAX_RETRY_AFTER_S))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        delta = (dt - datetime.now(UTC)).total_seconds()
        return max(0.05, min(delta, _MAX_RETRY_AFTER_S))
    except (TypeError, ValueError):
        return default


def _decode_json_object(resp: httpx.Response) -> dict[str, Any] | None:
    try:
        data = resp.json()
    except ValueError:
        log.warning("Wikimedia returned non-JSON response for %s", resp.url)
        return None
    return data if isinstance(data, dict) else None


class WikimediaClient:
    """Pooled, rate-limited async client for Wikimedia Action API + thumbnails."""

    def __init__(
        self,
        *,
        user_agent: str,
        limiter: AsyncTokenBucket,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 2,
    ) -> None:
        self._limiter = limiter
        self._max_retries = max(1, max_retries)
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent},
            transport=transport,
            timeout=httpx.Timeout(10.0),
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get_with_retry(
        self, url: str, params: dict[str, str] | None = None
    ) -> httpx.Response | None:
        for attempt in range(self._max_retries):
            await self._limiter.acquire()
            try:
                resp = await self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                log.warning("Wikimedia request error %s: %s", url, exc)
                return None
            if resp.status_code in (429, 503):
                if attempt + 1 >= self._max_retries:
                    return None
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                log.warning("%d from %s; backing off %.1fs", resp.status_code, url, retry_after)
                await asyncio.sleep(retry_after)
                continue
            if resp.status_code != 200:
                return None
            return resp
        return None

    async def _get_api_json(
        self, server_name: str, params: dict[str, str]
    ) -> dict[str, Any] | None:
        if not is_valid_server_name(server_name):
            return None
        url = f"https://{server_name}/w/api.php"
        for attempt in range(self._max_retries):
            resp = await self._get_with_retry(url, params)
            if resp is None:
                return None
            data = _decode_json_object(resp)
            if data is None:
                return None
            err = data.get("error")
            if isinstance(err, dict) and err.get("code") == "maxlag":
                if attempt + 1 >= self._max_retries:
                    return None
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"), default=1.0)
                log.warning("Wikimedia maxlag on %s; backing off %.1fs", server_name, retry_after)
                await asyncio.sleep(retry_after)
                continue
            return data
        return None

    async def _fetch_new_page_text(self, server_name: str, rev_id: int) -> tuple[str, str]:
        data = await self._get_api_json(
            server_name,
            {
                "action": "query",
                "prop": "revisions",
                "revids": str(rev_id),
                "rvprop": "content",
                "rvslots": "main",
                "format": "json",
                "formatversion": "2",
                "maxlag": str(MAXLAG_SECONDS),
            },
        )
        if data is None:
            return "", ""
        pages = data.get("query", {}).get("pages", [])
        if not pages:
            return "", ""
        revs = pages[0].get("revisions", [])
        if not revs:
            return "", ""
        content = revs[0].get("slots", {}).get("main", {}).get("content", "")
        return str(content)[:MAX_NEW_PAGE_CHARS].strip(), ""

    async def fetch_diff(self, server_name: str, old_rev: int, new_rev: int) -> tuple[str, str]:
        if not is_valid_server_name(server_name) or new_rev <= 0:
            return "", ""
        if old_rev <= 0:
            return await self._fetch_new_page_text(server_name, new_rev)

        data = await self._get_api_json(
            server_name,
            {
                "action": "compare",
                "fromrev": str(old_rev),
                "torev": str(new_rev),
                "prop": "diff",
                "format": "json",
                "maxlag": str(MAXLAG_SECONDS),
            },
        )
        if data is None:
            return "", ""
        compare = data.get("compare", {})
        return extract_diff_text(compare.get("*") or compare.get("body", ""))

    async def fetch_thumbnail(
        self, server_name: str, file_title: str, width: int = 512
    ) -> tuple[bytes, str]:
        if not is_valid_server_name(server_name) or not file_title:
            return b"", ""
        data = await self._get_api_json(
            server_name,
            {
                "action": "query",
                "prop": "imageinfo",
                "titles": file_title,
                "iiprop": "url|mime",
                "iiurlwidth": str(width),
                "format": "json",
                "maxlag": str(MAXLAG_SECONDS),
            },
        )
        if data is None:
            return b"", ""
        pages = data.get("query", {}).get("pages", {})
        if not isinstance(pages, dict):
            return b"", ""
        info_list = next(iter(pages.values()), {}).get("imageinfo") or [{}]
        info = info_list[0]
        thumb_url = info.get("thumburl")
        if not thumb_url:
            return b"", ""

        img = await self._get_with_retry(thumb_url)
        if img is None:
            return b"", ""
        mime = info.get("thumbmime") or img.headers.get("Content-Type") or "image/jpeg"
        return img.content, mime

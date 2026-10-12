"""Async HTTP fetching with retries, content-type filtering and size limits."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
DEFAULT_USER_AGENT = "zego-crawler/0.1"


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Outcome of fetching a single URL.

    Exactly one of ``body``, ``redirect_to`` or ``error`` is meaningful for a
    given result; ``is_html`` is False for successfully fetched non-HTML resources
    (whose bodies are deliberately never downloaded).
    """

    url: str
    status: int | None = None
    body: bytes | None = None
    encoding: str | None = None
    redirect_to: str | None = None
    is_html: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TextResult:
    """A small text resource such as robots.txt; ``status`` is None if the request failed."""

    status: int | None
    text: str = ""


@dataclass(frozen=True, slots=True)
class FetcherConfig:
    timeout: float = 10.0
    max_retries: int = 2
    backoff_base: float = 0.5
    max_body_bytes: int = 10 * 1024 * 1024
    max_connections: int = 10
    user_agent: str = DEFAULT_USER_AGENT


class Fetcher:
    """Thin wrapper around a shared :class:`httpx.AsyncClient`.

    A single client is used for the whole crawl so that TCP/TLS connections are
    pooled and re-used (HTTP keep-alive), which is the single biggest speed win
    when talking to one host.

    Redirects are not followed automatically. The crawler needs to see the
    ``Location`` so it can apply its same-domain rule and de-duplicate targets.
    """

    def __init__(self, config: FetcherConfig, transport: httpx.AsyncBaseTransport | None = None):
        self._config = config
        self._client = httpx.AsyncClient(
            timeout=config.timeout,
            follow_redirects=False,
            headers={"User-Agent": config.user_agent, "Accept": "text/html,*/*;q=0.1"},
            limits=httpx.Limits(
                max_connections=config.max_connections,
                max_keepalive_connections=config.max_connections,
            ),
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_text(self, url: str) -> TextResult:
        """Fetch a small text resource (e.g. robots.txt), following redirects."""
        try:
            response = await self._client.get(url, follow_redirects=True)
        except httpx.HTTPError as exc:
            logger.debug("GET %s failed: %s", url, exc)
            return TextResult(status=None)
        return TextResult(status=response.status_code, text=response.text)

    async def fetch(self, url: str) -> FetchResult:
        """Fetch ``url``, retrying transient failures with exponential backoff."""
        attempts = self._config.max_retries + 1
        result = FetchResult(url=url, error="not attempted")
        for attempt in range(attempts):
            result, retry_after = await self._fetch_once(url)
            retryable = result.error is not None and (
                result.status is None or result.status in RETRYABLE_STATUSES
            )
            if not retryable or attempt == attempts - 1:
                break
            delay = retry_after if retry_after is not None else self._backoff(attempt)
            logger.debug("Retrying %s in %.2fs (%s)", url, delay, result.error)
            await asyncio.sleep(delay)
        return result

    def _backoff(self, attempt: int) -> float:
        # Full jitter avoids many workers retrying in lock-step against a struggling server.
        return random.uniform(0, self._config.backoff_base * 2**attempt)

    async def _fetch_once(self, url: str) -> tuple[FetchResult, float | None]:
        try:
            async with self._client.stream("GET", url) as response:
                return await self._handle_response(url, response), _retry_after(response)
        except httpx.HTTPError as exc:
            return FetchResult(url=url, error=f"{type(exc).__name__}: {exc}"), None

    async def _handle_response(self, url: str, response: httpx.Response) -> FetchResult:
        status = response.status_code

        if status in REDIRECT_STATUSES:
            location = response.headers.get("Location")
            if not location:
                return FetchResult(url=url, status=status, error="redirect without Location")
            return FetchResult(url=url, status=status, redirect_to=location)

        if not response.is_success:
            return FetchResult(url=url, status=status, error=f"HTTP {status}")

        content_type = response.headers.get("Content-Type", "")
        mime = content_type.split(";", 1)[0].strip().lower()
        if mime not in HTML_CONTENT_TYPES:
            # Close without reading the body: no point downloading PDFs, images, etc.
            return FetchResult(url=url, status=status, is_html=False)

        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > self._config.max_body_bytes:
                return FetchResult(url=url, status=status, error="response body too large")

        return FetchResult(
            url=url,
            status=status,
            body=bytes(body),
            encoding=response.charset_encoding,
            is_html=True,
        )


def _retry_after(response: httpx.Response, cap: float = 30.0) -> float | None:
    """Parse a numeric ``Retry-After`` header (HTTP-date form is ignored)."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return min(max(float(value), 0.0), cap)
    except ValueError:
        return None

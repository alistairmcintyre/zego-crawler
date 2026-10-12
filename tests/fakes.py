"""In-memory test doubles shared across unit tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from crawler.fetcher import FetchResult


def html(*hrefs: str) -> bytes:
    anchors = "".join(f'<a href="{href}">link</a>' for href in hrefs)
    return f"<html><body>{anchors}</body></html>".encode()


@dataclass
class FakeFetcher:
    """Serves canned :class:`FetchResult`s keyed by URL; unknown URLs are 404s.

    Records every fetch and the peak number of concurrent in-flight fetches so
    tests can assert on de-duplication and parallelism.
    """

    pages: dict[str, FetchResult] = field(default_factory=dict)
    delay: float = 0.0
    fetched: list[str] = field(default_factory=list)
    in_flight: int = 0
    peak_in_flight: int = 0

    def add_html(self, url: str, *hrefs: str) -> None:
        self.pages[url] = FetchResult(url=url, status=200, body=html(*hrefs), is_html=True)

    def add(self, result: FetchResult) -> None:
        self.pages[result.url] = result

    async def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return self.pages.get(url, FetchResult(url=url, status=404, error="HTTP 404"))
        finally:
            self.in_flight -= 1

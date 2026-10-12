"""The crawl orchestrator: a bounded pool of async workers sharing a URL frontier."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from crawler.fetcher import FetchResult
from crawler.parser import extract_links
from crawler.urls import host_of, is_same_host, normalise_url, origin_of

logger = logging.getLogger(__name__)


class PageFetcher(Protocol):
    async def fetch(self, url: str) -> FetchResult: ...


class UrlPolicy(Protocol):
    async def load(self, origin: str) -> None: ...

    def allows(self, url: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class PageResult:
    """What the crawler reports for each page it visits."""

    url: str
    links: tuple[str, ...] = ()
    status: int | None = None
    error: str | None = None
    redirect: bool = False


@dataclass(slots=True)
class CrawlStats:
    pages_reported: int = 0
    non_html_skipped: int = 0
    errors: int = 0
    disallowed_by_robots: int = 0
    limit_reached: bool = False


@dataclass(frozen=True, slots=True)
class CrawlerConfig:
    concurrency: int = 10
    max_pages: int | None = None

    def __post_init__(self) -> None:
        if self.concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if self.max_pages is not None and self.max_pages < 1:
            raise ValueError("max_pages must be >= 1")


@dataclass(slots=True)
class _Frontier:
    """URLs waiting to be fetched plus everything we have ever scheduled."""

    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    seen: set[str] = field(default_factory=set)


class Crawler:
    """Breadth-first crawl of a single host.

    ``concurrency`` workers pull URLs from a shared :class:`asyncio.Queue`. Each
    URL is scheduled at most once (the ``seen`` set is updated at enqueue time,
    not fetch time, so two workers can never race to fetch the same page).
    The crawl ends when the queue is drained and every worker is idle.

    Results are pushed to ``on_page`` as soon as each page completes, so output
    streams rather than being buffered until the end of the crawl.

    If the start URL redirects to another host (e.g. ``example.com`` to
    ``www.example.com``), the crawl moves to that host. Redirects found later in
    the crawl are held to the normal same-host rule.
    """

    def __init__(
        self,
        start_url: str,
        fetcher: PageFetcher,
        on_page: Callable[[PageResult], None],
        config: CrawlerConfig | None = None,
        policy: UrlPolicy | None = None,
    ):
        normalised = normalise_url(start_url)
        if normalised is None:
            raise ValueError(f"Not a valid http(s) URL: {start_url!r}")
        self.start_url = normalised
        self.host = host_of(normalised)
        # The URL at the end of the start URL's redirect chain so far.
        self._entry_url = normalised
        self._fetcher = fetcher
        self._on_page = on_page
        self._config = config or CrawlerConfig()
        self._policy = policy
        self._frontier = _Frontier()
        self.stats = CrawlStats()

    async def run(self) -> CrawlStats:
        await self._load_policy()
        self._schedule(self.start_url)
        workers = [
            asyncio.create_task(self._worker(), name=f"crawler-worker-{i}")
            for i in range(self._config.concurrency)
        ]
        try:
            await self._frontier.queue.join()
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        return self.stats

    def _schedule(self, url: str) -> None:
        frontier = self._frontier
        if url in frontier.seen or not is_same_host(url, self.host):
            return
        max_pages = self._config.max_pages
        if max_pages is not None and len(frontier.seen) >= max_pages:
            self.stats.limit_reached = True
            return
        if self._policy is not None and not self._policy.allows(url):
            frontier.seen.add(url)  # don't re-evaluate it every time it's linked
            self.stats.disallowed_by_robots += 1
            logger.debug("Disallowed by robots.txt: %s", url)
            return
        frontier.seen.add(url)
        frontier.queue.put_nowait(url)

    async def _worker(self) -> None:
        queue = self._frontier.queue
        while True:
            url = await queue.get()
            try:
                await self._process(url)
            except Exception:
                # One bad page must never take a worker (and so the crawl) down.
                logger.exception("Unexpected error processing %s", url)
                self.stats.errors += 1
            finally:
                queue.task_done()

    async def _process(self, url: str) -> None:
        result = await self._fetcher.fetch(url)

        if result.error is not None:
            self.stats.errors += 1
            self._report(PageResult(url=url, status=result.status, error=result.error))
            return

        if result.redirect_to is not None:
            target = normalise_url(result.redirect_to, url)
            self._report(
                PageResult(
                    url=url,
                    links=(target,) if target else (),
                    status=result.status,
                    redirect=True,
                )
            )
            if target:
                if url == self._entry_url:
                    await self._follow_entry_redirect(target)
                self._schedule(target)
            return

        if not result.is_html or result.body is None:
            self.stats.non_html_skipped += 1
            logger.debug("Skipping non-HTML resource %s", url)
            return

        # lxml releases the GIL while parsing, so a thread keeps the event loop
        # free to service other in-flight requests during CPU-bound work.
        links = await asyncio.to_thread(extract_links, result.body, url, result.encoding)
        self._report(PageResult(url=url, links=tuple(links), status=result.status))
        for link in links:
            self._schedule(link)

    async def _follow_entry_redirect(self, target: str) -> None:
        """Move the crawl to the host the start URL redirects to.

        No locking is needed: while the start URL's redirect chain is being
        followed, it is the only URL in flight.
        """
        self._entry_url = target
        new_host = host_of(target)
        if new_host != self.host:
            logger.info("Start URL redirects to %s; crawling that host instead", new_host)
            self.host = new_host
            await self._load_policy()

    async def _load_policy(self) -> None:
        if self._policy is not None:
            await self._policy.load(origin_of(self._entry_url))

    def _report(self, page: PageResult) -> None:
        self.stats.pages_reported += 1
        self._on_page(page)

"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from crawler.crawler import Crawler, CrawlerConfig, CrawlStats
from crawler.fetcher import DEFAULT_USER_AGENT, Fetcher, FetcherConfig
from crawler.reporters import JsonLinesReporter, TextReporter
from crawler.robots import AllowAll, RobotsPolicy
from crawler.urls import normalise_url, origin_of

logger = logging.getLogger("crawler")

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


def _int_at_least(minimum: int) -> Callable[[str], int]:
    """Build an argparse ``type`` that accepts whole numbers >= ``minimum``."""

    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"must be a whole number, but got {value!r}") from None
        if number < minimum:
            raise argparse.ArgumentTypeError(f"must be >= {minimum}, but got {number}")
        return number

    return parse


def _positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a number, but got {value!r}") from None
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError(f"must be a finite positive number, but got {value!r}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crawler",
        description=(
            "Crawl every page on a single host, printing each page's URL followed by "
            "the URLs linked from it. Other domains and subdomains are not crawled."
        ),
    )
    parser.add_argument("url", help="base URL to start crawling from, e.g. https://example.com")
    parser.add_argument(
        "-c",
        "--concurrency",
        type=_int_at_least(1),
        default=10,
        help="maximum number of simultaneous requests (default: %(default)s)",
    )
    parser.add_argument(
        "-n",
        "--max-pages",
        type=_int_at_least(1),
        default=None,
        help="stop scheduling new pages after this many (default: unlimited)",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=_positive_float,
        default=10.0,
        help="per-request timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "-r",
        "--retries",
        type=_int_at_least(0),
        default=2,
        help="retries for transient failures (default: %(default)s)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("text", "jsonl"),
        default="text",
        help="output format (default: %(default)s)",
    )
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="do not honour robots.txt",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent header to send (default: %(default)s)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="increase log verbosity on stderr (-v info, -vv debug)",
    )
    return parser


async def crawl(args: argparse.Namespace, out: TextIO) -> CrawlStats:
    reporter: TextReporter | JsonLinesReporter = (
        JsonLinesReporter(out) if args.format == "jsonl" else TextReporter(out)
    )
    fetcher_config = FetcherConfig(
        timeout=args.timeout,
        max_retries=args.retries,
        max_connections=args.concurrency,
        user_agent=args.user_agent,
    )
    async with Fetcher(fetcher_config) as fetcher:
        policy: RobotsPolicy | AllowAll = AllowAll()
        if not args.ignore_robots:
            policy = RobotsPolicy(args.user_agent)
            await policy.load(origin_of(args.url), fetcher)
        crawler = Crawler(
            args.url,
            fetcher=fetcher,
            on_page=reporter,
            config=CrawlerConfig(concurrency=args.concurrency, max_pages=args.max_pages),
            policy=policy,
        )
        return await crawler.run()


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out = out or sys.stdout

    logging.basicConfig(
        level=[logging.WARNING, logging.INFO, logging.DEBUG][min(args.verbose, 2)],
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if normalise_url(args.url) is None:
        parser.error(f"not a valid http(s) URL: {args.url!r}")

    try:
        stats = asyncio.run(crawl(args, out))
    except KeyboardInterrupt:
        logger.warning("Interrupted")
        return EXIT_INTERRUPTED

    logger.info(
        "Done: %d pages, %d errors, %d non-HTML skipped, %d disallowed by robots.txt%s",
        stats.pages_reported,
        stats.errors,
        stats.non_html_skipped,
        stats.disallowed_by_robots,
        " (page limit reached)" if stats.limit_reached else "",
    )
    return EXIT_OK

"""A fast, concurrent, single-domain web crawler."""

from crawler.crawler import Crawler, CrawlerConfig, CrawlStats, PageResult

__all__ = ["CrawlStats", "Crawler", "CrawlerConfig", "PageResult"]
__version__ = "0.1.0"

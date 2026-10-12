import pytest

from crawler.crawler import Crawler, CrawlerConfig, PageResult
from crawler.fetcher import FetchResult
from tests.fakes import FakeFetcher

ROOT = "https://example.com/"


class DenyPrefix:
    """Test policy: blocks URLs starting with ``prefix`` and records each origin loaded."""

    def __init__(self, prefix: str = "never-matches"):
        self.prefix = prefix
        self.loaded: list[str] = []

    async def load(self, origin: str) -> None:
        self.loaded.append(origin)

    def allows(self, url: str) -> bool:
        return not url.startswith(self.prefix)


def make_crawler(
    fetcher: FakeFetcher,
    start: str = ROOT,
    config: CrawlerConfig | None = None,
    policy: DenyPrefix | None = None,
) -> tuple[Crawler, list[PageResult]]:
    results: list[PageResult] = []
    crawler = Crawler(start, fetcher=fetcher, on_page=results.append, config=config, policy=policy)
    return crawler, results


def by_url(results: list[PageResult]) -> dict[str, PageResult]:
    return {r.url: r for r in results}


async def test_crawls_every_reachable_page_on_the_host() -> None:
    fetcher = FakeFetcher()
    fetcher.add_html(ROOT, "/a", "/b")
    fetcher.add_html("https://example.com/a", "/c")
    fetcher.add_html("https://example.com/b", "/")
    fetcher.add_html("https://example.com/c")
    crawler, results = make_crawler(fetcher)

    stats = await crawler.run()

    assert set(by_url(results)) == {
        ROOT,
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    }
    assert by_url(results)[ROOT].links == ("https://example.com/a", "https://example.com/b")
    assert stats.pages_reported == 4
    assert stats.errors == 0


async def test_each_url_is_fetched_once_despite_cycles_and_duplicates() -> None:
    fetcher = FakeFetcher()
    fetcher.add_html(ROOT, "/a", "/a#frag", "/b")
    fetcher.add_html("https://example.com/a", "/", "/b")
    fetcher.add_html("https://example.com/b", "/a", "/")
    crawler, _ = make_crawler(fetcher, config=CrawlerConfig(concurrency=5))

    await crawler.run()

    assert sorted(fetcher.fetched) == sorted(set(fetcher.fetched))
    assert len(fetcher.fetched) == 3


async def test_external_and_subdomain_links_are_reported_but_not_crawled() -> None:
    fetcher = FakeFetcher()
    fetcher.add_html(
        ROOT, "https://other.com/", "https://www.example.com/", "https://blog.example.com/x"
    )
    crawler, results = make_crawler(fetcher)

    await crawler.run()

    assert fetcher.fetched == [ROOT]
    assert results[0].links == (
        "https://other.com/",
        "https://www.example.com/",
        "https://blog.example.com/x",
    )


async def test_start_url_is_normalised() -> None:
    fetcher = FakeFetcher()
    fetcher.add_html(ROOT)
    crawler, _ = make_crawler(fetcher, start="HTTPS://EXAMPLE.com:443#top")
    await crawler.run()
    assert fetcher.fetched == [ROOT]


def test_invalid_start_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="Not a valid"):
        Crawler("ftp://example.com", fetcher=FakeFetcher(), on_page=lambda _: None)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [({"concurrency": 0}, "concurrency"), ({"max_pages": 0}, "max_pages")],
)
def test_config_validation(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        CrawlerConfig(**kwargs)


async def test_fetches_run_concurrently_up_to_the_limit() -> None:
    fetcher = FakeFetcher(delay=0.01)
    children = [f"/p{i}" for i in range(20)]
    fetcher.add_html(ROOT, *children)
    for child in children:
        fetcher.add_html(f"https://example.com{child}")
    crawler, results = make_crawler(fetcher, config=CrawlerConfig(concurrency=4))

    await crawler.run()

    assert len(results) == 21
    assert fetcher.peak_in_flight == 4


async def test_max_pages_caps_the_crawl() -> None:
    fetcher = FakeFetcher()
    fetcher.add_html(ROOT, *[f"/p{i}" for i in range(10)])
    crawler, results = make_crawler(fetcher, config=CrawlerConfig(max_pages=3))

    stats = await crawler.run()

    assert len(fetcher.fetched) == 3
    assert len(results) == 3
    assert stats.limit_reached


async def test_errors_are_reported_and_do_not_stop_the_crawl() -> None:
    fetcher = FakeFetcher()
    fetcher.add_html(ROOT, "/missing", "/ok")
    fetcher.add_html("https://example.com/ok")
    crawler, results = make_crawler(fetcher)

    stats = await crawler.run()

    missing = by_url(results)["https://example.com/missing"]
    assert missing.error == "HTTP 404"
    assert missing.status == 404
    assert "https://example.com/ok" in by_url(results)
    assert stats.errors == 1


async def test_same_host_redirect_is_followed() -> None:
    fetcher = FakeFetcher()
    fetcher.add_html(ROOT, "/old")
    fetcher.add(FetchResult(url="https://example.com/old", status=301, redirect_to="/new"))
    fetcher.add_html("https://example.com/new")
    crawler, results = make_crawler(fetcher)

    await crawler.run()

    old = by_url(results)["https://example.com/old"]
    assert old.redirect
    assert old.links == ("https://example.com/new",)
    assert "https://example.com/new" in fetcher.fetched


async def test_off_host_redirect_is_reported_but_not_followed() -> None:
    fetcher = FakeFetcher()
    fetcher.add_html(ROOT, "/out")
    fetcher.add(
        FetchResult(url="https://example.com/out", status=302, redirect_to="https://other.com/")
    )
    crawler, results = make_crawler(fetcher)

    await crawler.run()

    assert by_url(results)["https://example.com/out"].links == ("https://other.com/",)
    assert "https://other.com/" not in fetcher.fetched


async def test_redirect_to_uncrawlable_location_has_no_links() -> None:
    fetcher = FakeFetcher()
    fetcher.add(FetchResult(url=ROOT, status=302, redirect_to="mailto:x@example.com"))
    crawler, results = make_crawler(fetcher)
    await crawler.run()
    assert results == [PageResult(url=ROOT, links=(), status=302, redirect=True)]


async def test_non_html_resources_are_skipped_silently() -> None:
    fetcher = FakeFetcher()
    fetcher.add_html(ROOT, "/doc.pdf")
    fetcher.add(FetchResult(url="https://example.com/doc.pdf", status=200, is_html=False))
    crawler, results = make_crawler(fetcher)

    stats = await crawler.run()

    assert [r.url for r in results] == [ROOT]
    assert stats.non_html_skipped == 1


async def test_policy_blocks_disallowed_urls() -> None:
    fetcher = FakeFetcher()
    fetcher.add_html(ROOT, "/private/a", "/private/b", "/public")
    fetcher.add_html("https://example.com/public", "/private/a")
    crawler, _ = make_crawler(fetcher, policy=DenyPrefix("https://example.com/private"))

    stats = await crawler.run()

    assert sorted(fetcher.fetched) == [ROOT, "https://example.com/public"]
    assert stats.disallowed_by_robots == 2  # counted once per URL, not per link


async def test_unexpected_exception_does_not_kill_workers() -> None:
    class ExplodingFetcher(FakeFetcher):
        async def fetch(self, url: str) -> FetchResult:
            if url.endswith("/boom"):
                raise RuntimeError("kaboom")
            return await super().fetch(url)

    fetcher = ExplodingFetcher()
    fetcher.add_html(ROOT, "/boom", "/fine")
    fetcher.add_html("https://example.com/fine")
    crawler, results = make_crawler(fetcher, config=CrawlerConfig(concurrency=1))

    stats = await crawler.run()

    assert "https://example.com/fine" in by_url(results)
    assert stats.errors == 1


async def test_start_url_redirect_to_another_host_moves_the_crawl() -> None:
    fetcher = FakeFetcher()
    fetcher.add(FetchResult(url=ROOT, status=301, redirect_to="https://www.example.com/"))
    fetcher.add_html("https://www.example.com/", "/about", "https://example.com/other")
    fetcher.add_html("https://www.example.com/about")
    policy = DenyPrefix()
    crawler, results = make_crawler(fetcher, policy=policy)

    await crawler.run()

    assert crawler.host == "www.example.com"
    assert [r.url for r in results] == [
        ROOT,
        "https://www.example.com/",
        "https://www.example.com/about",
    ]
    assert "https://example.com/other" not in fetcher.fetched  # old host is now off-site
    assert policy.loaded == ["https://example.com", "https://www.example.com"]


async def test_start_url_redirect_chain_is_followed_to_the_end() -> None:
    fetcher = FakeFetcher()
    fetcher.add(
        FetchResult(url="http://example.com/", status=301, redirect_to="https://example.com/")
    )
    fetcher.add(FetchResult(url=ROOT, status=301, redirect_to="https://www.example.com/"))
    fetcher.add_html("https://www.example.com/")
    policy = DenyPrefix()
    crawler, _ = make_crawler(fetcher, start="http://example.com", policy=policy)

    await crawler.run()

    assert crawler.host == "www.example.com"
    assert fetcher.fetched[-1] == "https://www.example.com/"
    # http -> https on the same host doesn't reload robots.txt; the host change does.
    assert policy.loaded == ["http://example.com", "https://www.example.com"]


async def test_start_url_redirect_policy_still_applies_on_the_new_host() -> None:
    fetcher = FakeFetcher()
    fetcher.add(FetchResult(url=ROOT, status=301, redirect_to="https://www.example.com/"))
    fetcher.add_html("https://www.example.com/", "/private/x", "/public")
    fetcher.add_html("https://www.example.com/public")
    crawler, _ = make_crawler(fetcher, policy=DenyPrefix("https://www.example.com/private"))

    stats = await crawler.run()

    assert "https://www.example.com/public" in fetcher.fetched
    assert stats.disallowed_by_robots == 1


async def test_later_redirects_to_another_host_do_not_move_the_crawl() -> None:
    fetcher = FakeFetcher()
    fetcher.add_html(ROOT, "/go")
    fetcher.add(
        FetchResult(
            url="https://example.com/go", status=302, redirect_to="https://www.example.com/"
        )
    )
    crawler, _ = make_crawler(fetcher)

    await crawler.run()

    assert crawler.host == "example.com"
    assert "https://www.example.com/" not in fetcher.fetched

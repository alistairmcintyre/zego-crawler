from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from crawler.fetcher import Fetcher, FetcherConfig, TextResult, _retry_after

URL = "https://example.com/page"


@pytest.fixture
async def fetcher() -> AsyncIterator[Fetcher]:
    async with Fetcher(FetcherConfig(max_retries=2, backoff_base=0, max_body_bytes=1024)) as f:
        yield f


@respx.mock
async def test_html_page_returns_body_and_encoding(fetcher: Fetcher) -> None:
    respx.get(URL).respond(
        200, content=b"<a href='/x'>x</a>", headers={"Content-Type": "text/html; charset=utf-8"}
    )
    result = await fetcher.fetch(URL)
    assert result.is_html
    assert result.status == 200
    assert result.body == b"<a href='/x'>x</a>"
    assert result.encoding == "utf-8"
    assert result.error is None


@respx.mock
async def test_xhtml_is_treated_as_html(fetcher: Fetcher) -> None:
    respx.get(URL).respond(
        200, content=b"<html/>", headers={"Content-Type": "application/xhtml+xml"}
    )
    assert (await fetcher.fetch(URL)).is_html


@respx.mock
async def test_non_html_body_is_not_downloaded(fetcher: Fetcher) -> None:
    respx.get(URL).respond(200, content=b"%PDF-1.7", headers={"Content-Type": "application/pdf"})
    result = await fetcher.fetch(URL)
    assert not result.is_html
    assert result.body is None
    assert result.error is None


@respx.mock
async def test_missing_content_type_is_not_html(fetcher: Fetcher) -> None:
    respx.get(URL).respond(200, content=b"???")
    assert not (await fetcher.fetch(URL)).is_html


@respx.mock
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_redirect_is_reported_not_followed(fetcher: Fetcher, status: int) -> None:
    route = respx.get(URL).respond(status, headers={"Location": "/elsewhere"})
    result = await fetcher.fetch(URL)
    assert result.redirect_to == "/elsewhere"
    assert result.status == status
    assert route.call_count == 1


@respx.mock
async def test_redirect_without_location_is_an_error(fetcher: Fetcher) -> None:
    respx.get(URL).respond(302)
    result = await fetcher.fetch(URL)
    assert result.error == "redirect without Location"


@respx.mock
async def test_client_error_is_not_retried(fetcher: Fetcher) -> None:
    route = respx.get(URL).respond(404)
    result = await fetcher.fetch(URL)
    assert result.error == "HTTP 404"
    assert result.status == 404
    assert route.call_count == 1


@respx.mock
async def test_transient_server_error_is_retried_until_success(fetcher: Fetcher) -> None:
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(502),
            httpx.Response(200, content=b"<html/>", headers={"Content-Type": "text/html"}),
        ]
    )
    result = await fetcher.fetch(URL)
    assert result.is_html
    assert route.call_count == 3


@respx.mock
async def test_gives_up_after_max_retries(fetcher: Fetcher) -> None:
    route = respx.get(URL).respond(500)
    result = await fetcher.fetch(URL)
    assert result.error == "HTTP 500"
    assert route.call_count == 3  # 1 attempt + 2 retries


@respx.mock
async def test_transport_errors_are_retried_and_reported(fetcher: Fetcher) -> None:
    route = respx.get(URL).mock(side_effect=httpx.ConnectTimeout("timed out"))
    result = await fetcher.fetch(URL)
    assert result.status is None
    assert result.error is not None
    assert "ConnectTimeout" in result.error
    assert route.call_count == 3


@respx.mock
async def test_honours_numeric_retry_after(fetcher: Fetcher) -> None:
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, content=b"<html/>", headers={"Content-Type": "text/html"}),
        ]
    )
    assert (await fetcher.fetch(URL)).is_html
    assert route.call_count == 2


@respx.mock
async def test_oversized_body_is_abandoned(fetcher: Fetcher) -> None:
    respx.get(URL).respond(200, content=b"x" * 2048, headers={"Content-Type": "text/html"})
    result = await fetcher.fetch(URL)
    assert result.error == "response body too large"
    assert result.body is None


@respx.mock
async def test_sends_configured_user_agent() -> None:
    route = respx.get(URL).respond(200, headers={"Content-Type": "text/html"})
    async with Fetcher(FetcherConfig(user_agent="test-agent/1.0")) as fetcher:
        await fetcher.fetch(URL)
    assert route.calls.last.request.headers["User-Agent"] == "test-agent/1.0"


@respx.mock
async def test_get_text(fetcher: Fetcher) -> None:
    respx.get("https://example.com/robots.txt").respond(200, text="User-agent: *\nDisallow:")
    respx.get("https://example.com/missing.txt").respond(404)
    respx.get("https://example.com/broken.txt").mock(side_effect=httpx.ConnectError("boom"))
    assert await fetcher.get_text("https://example.com/robots.txt") == TextResult(
        status=200, text="User-agent: *\nDisallow:"
    )
    assert (await fetcher.get_text("https://example.com/missing.txt")).status == 404
    assert await fetcher.get_text("https://example.com/broken.txt") == TextResult(status=None)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("5", 5.0),
        ("-3", 0.0),
        ("9999", 30.0),
        ("Wed, 21 Oct 2015 07:28:00 GMT", None),
    ],
)
def test_retry_after_parsing(header: str | None, expected: float | None) -> None:
    headers = {"Retry-After": header} if header is not None else {}
    assert _retry_after(httpx.Response(429, headers=headers)) == expected

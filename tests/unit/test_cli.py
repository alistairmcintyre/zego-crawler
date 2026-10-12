import io
from collections.abc import Coroutine
from typing import Any
from unittest.mock import patch

import pytest
import respx

from crawler.cli import EXIT_INTERRUPTED, EXIT_OK, build_parser, main


def test_defaults() -> None:
    args = build_parser().parse_args(["https://example.com"])
    assert args.concurrency == 10
    assert args.max_pages is None
    assert args.format == "text"
    assert not args.ignore_robots


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["not-a-url"],
        ["mailto:x@example.com"],
        ["https://example.com", "--concurrency", "0"],
        ["https://example.com", "--max-pages", "-1"],
        ["https://example.com", "--timeout", "0"],
        ["https://example.com", "--format", "xml"],
        ["https://example.com", "--concurrency", "abc"],
        ["https://example.com", "--concurrency", "1.5"],
        ["https://example.com", "--retries", "-1"],
        ["https://example.com", "--timeout", "abc"],
        ["https://example.com", "--timeout", "nan"],
        ["https://example.com", "--timeout", "inf"],
    ],
)
def test_invalid_arguments_exit_with_usage_error(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    assert "_int_at_least" not in capsys.readouterr().err  # no internal names leak


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["-c", "abc"], "must be a whole number, but got 'abc'"),
        (["-c", "0"], "must be >= 1, but got 0"),
        (["-r", "-1"], "must be >= 0, but got -1"),
        (["-t", "nan"], "must be a finite positive number, but got 'nan'"),
    ],
)
def test_invalid_number_messages(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(["https://example.com", *argv])
    assert message in capsys.readouterr().err


def test_zero_retries_is_allowed() -> None:
    assert build_parser().parse_args(["https://example.com", "-r", "0"]).retries == 0


@respx.mock
def test_end_to_end_with_mocked_http() -> None:
    respx.get("https://example.com/robots.txt").respond(200, text="User-agent: *\nDisallow: /no\n")
    respx.get("https://example.com/").respond(
        200,
        html='<a href="/a">a</a><a href="/no">no</a><a href="https://x.com/">x</a>',
    )
    respx.get("https://example.com/a").respond(200, html="<p>leaf</p>")
    out = io.StringIO()

    code = main(["https://example.com", "-c", "2"], out=out)

    assert code == EXIT_OK
    assert out.getvalue().splitlines() == [
        "https://example.com/",
        "  - https://example.com/a",
        "  - https://example.com/no",
        "  - https://x.com/",
        "https://example.com/a",
    ]


@respx.mock
def test_start_url_redirect_to_www_uses_the_new_hosts_robots() -> None:
    respx.get("https://example.com/robots.txt").respond(404)
    respx.get("https://example.com/").respond(301, headers={"Location": "https://www.example.com/"})
    respx.get("https://www.example.com/robots.txt").respond(
        200, text="User-agent: *\nDisallow: /private\n"
    )
    respx.get("https://www.example.com/").respond(
        200, html='<a href="/a">a</a><a href="/private">p</a>'
    )
    respx.get("https://www.example.com/a").respond(200, html="<p>leaf</p>")
    out = io.StringIO()

    assert main(["https://example.com"], out=out) == EXIT_OK

    assert out.getvalue().splitlines() == [
        "https://example.com/",
        "  => https://www.example.com/",
        "https://www.example.com/",
        "  - https://www.example.com/a",
        "  - https://www.example.com/private",
        "https://www.example.com/a",
    ]


@respx.mock
def test_ignore_robots_skips_robots_fetch() -> None:
    robots = respx.get("https://example.com/robots.txt").respond(
        200, text="User-agent: *\nDisallow: /"
    )
    respx.get("https://example.com/").respond(200, html="<p>hi</p>")
    out = io.StringIO()

    assert main(["https://example.com", "--ignore-robots", "-f", "jsonl", "-vv"], out=out) == 0

    assert not robots.called
    assert '"url": "https://example.com/"' in out.getvalue()


def test_keyboard_interrupt_exits_cleanly() -> None:
    def interrupt(coro: Coroutine[Any, Any, Any]) -> None:
        coro.close()
        raise KeyboardInterrupt

    with patch("crawler.cli.asyncio.run", side_effect=interrupt):
        assert main(["https://example.com"], out=io.StringIO()) == EXIT_INTERRUPTED

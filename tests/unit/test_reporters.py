import io
import json

from crawler.crawler import PageResult
from crawler.reporters import JsonLinesReporter, TextReporter


def test_text_reporter_lists_links() -> None:
    out = io.StringIO()
    TextReporter(out)(PageResult(url="https://e.com/", links=("https://e.com/a", "https://x.com/")))
    assert out.getvalue() == "https://e.com/\n  - https://e.com/a\n  - https://x.com/\n"


def test_text_reporter_page_without_links() -> None:
    out = io.StringIO()
    TextReporter(out)(PageResult(url="https://e.com/"))
    assert out.getvalue() == "https://e.com/\n"


def test_text_reporter_redirect() -> None:
    out = io.StringIO()
    TextReporter(out)(
        PageResult(url="https://e.com/old", links=("https://e.com/new",), redirect=True)
    )
    assert out.getvalue() == "https://e.com/old\n  => https://e.com/new\n"


def test_text_reporter_error() -> None:
    out = io.StringIO()
    TextReporter(out)(PageResult(url="https://e.com/x", status=404, error="HTTP 404"))
    assert out.getvalue() == "https://e.com/x\n  ! error: HTTP 404\n"


def test_json_lines_reporter() -> None:
    out = io.StringIO()
    reporter = JsonLinesReporter(out)
    reporter(PageResult(url="https://e.com/", links=("https://e.com/a",), status=200))
    reporter(PageResult(url="https://e.com/a", status=500, error="HTTP 500"))

    records = [json.loads(line) for line in out.getvalue().splitlines()]
    assert records == [
        {
            "url": "https://e.com/",
            "status": 200,
            "links": ["https://e.com/a"],
            "redirect": False,
            "error": None,
        },
        {
            "url": "https://e.com/a",
            "status": 500,
            "links": [],
            "redirect": False,
            "error": "HTTP 500",
        },
    ]

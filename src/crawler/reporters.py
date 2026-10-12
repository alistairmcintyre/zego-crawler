"""Output formats for crawl results."""

from __future__ import annotations

import json
from typing import TextIO

from crawler.crawler import PageResult


class TextReporter:
    """Human-readable output: the page URL followed by an indented list of its links."""

    def __init__(self, stream: TextIO):
        self._stream = stream

    def __call__(self, page: PageResult) -> None:
        lines = [page.url]
        if page.error is not None:
            lines.append(f"  ! error: {page.error}")
        elif page.redirect:
            lines.extend(f"  => {link}" for link in page.links)
        else:
            lines.extend(f"  - {link}" for link in page.links)
        self._stream.write("\n".join(lines) + "\n")
        self._stream.flush()


class JsonLinesReporter:
    """One JSON object per page; easy to pipe into ``jq`` or a downstream loader."""

    def __init__(self, stream: TextIO):
        self._stream = stream

    def __call__(self, page: PageResult) -> None:
        record = {
            "url": page.url,
            "status": page.status,
            "links": list(page.links),
            "redirect": page.redirect,
            "error": page.error,
        }
        self._stream.write(json.dumps(record) + "\n")
        self._stream.flush()

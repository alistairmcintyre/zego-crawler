"""End-to-end crawls of a real (local) website over real HTTP."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from typing import Any

import pytest

from crawler.cli import main

pytestmark = pytest.mark.integration


def crawl_jsonl(*argv: str) -> dict[str, dict[str, Any]]:
    out = io.StringIO()
    assert main([*argv, "--format", "jsonl"], out=out) == 0
    records = [json.loads(line) for line in out.getvalue().splitlines()]
    return {record["url"]: record for record in records}


def test_crawls_whole_site_respecting_scope_and_robots(site_url: str) -> None:
    pages = crawl_jsonl(site_url)

    assert set(pages) == {
        f"{site_url}/",
        f"{site_url}/index.html",  # same content as "/", but a distinct URL
        f"{site_url}/about.html",
        f"{site_url}/blog",  # 301 -> /blog/ from the server
        f"{site_url}/blog/",
        f"{site_url}/blog/post-1.html",
        f"{site_url}/blog/post-2.html",
        f"{site_url}/missing.html",
    }

    home = pages[f"{site_url}/"]
    assert home["status"] == 200
    assert home["links"] == [
        f"{site_url}/about.html",
        f"{site_url}/blog",
        f"{site_url}/docs/guide.pdf",
        f"{site_url}/private/secret.html",
        f"{site_url}/missing.html",
        "https://external.example.org/page",
        "http://sub.localhost:1/",
    ]

    redirect = pages[f"{site_url}/blog"]
    assert redirect["redirect"] is True
    assert redirect["links"] == [f"{site_url}/blog/"]

    assert pages[f"{site_url}/blog/"]["links"] == [
        f"{site_url}/blog/post-1.html",
        f"{site_url}/blog/post-2.html",
        f"{site_url}/about.html",
    ]
    # "#team" is an in-page anchor, so it normalises to a self-link.
    assert pages[f"{site_url}/about.html"]["links"] == [
        f"{site_url}/index.html",
        f"{site_url}/about.html",
    ]
    assert pages[f"{site_url}/missing.html"]["error"] == "HTTP 404"


def test_ignore_robots_crawls_private_section(site_url: str) -> None:
    pages = crawl_jsonl(site_url, "--ignore-robots")
    assert f"{site_url}/private/secret.html" in pages
    assert pages[f"{site_url}/private/deeper.html"]["error"] == "HTTP 404"


def test_max_pages(site_url: str) -> None:
    assert len(crawl_jsonl(site_url, "--max-pages", "2")) == 2


def test_runs_as_installed_module(site_url: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "crawler", site_url, "--max-pages", "1"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert proc.stdout.splitlines()[0] == f"{site_url}/"
    assert f"  - {site_url}/about.html" in proc.stdout

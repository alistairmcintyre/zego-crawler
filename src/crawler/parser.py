"""Extract hyperlinks from an HTML document."""

from __future__ import annotations

import logging

import lxml.etree
import lxml.html

from crawler.urls import normalise_url

logger = logging.getLogger(__name__)


def extract_links(body: bytes, page_url: str, encoding: str | None = None) -> list[str]:
    """Return the unique, normalised, absolute URLs of all ``<a href>`` links in ``body``.

    Links are returned in document order. Relative links are resolved against the
    document's ``<base href>`` if it has one, otherwise against ``page_url``.
    Links to other domains are *included*: scoping is the crawler's concern, the
    parser just reports what is on the page.

    When ``encoding`` (from the ``Content-Type`` header) is given, the body is decoded
    with Python's codecs, which know far more aliases than libxml2. Otherwise the
    raw bytes go to lxml so it can honour ``<meta charset>``.
    """
    if not body.strip():
        return []

    try:
        doc = lxml.html.document_fromstring(_decode(body, encoding))
    except (lxml.etree.ParserError, ValueError) as exc:
        logger.debug("Could not parse %s: %s", page_url, exc)
        return []

    base_url = page_url
    base = doc.find(".//base[@href]")
    if base is not None:
        base_url = normalise_url(base.get("href", ""), page_url) or page_url

    seen: dict[str, None] = {}  # dict preserves insertion order
    for anchor in doc.iter("a"):
        href = anchor.get("href")
        if href is None:
            continue
        url = normalise_url(href, base_url)
        if url is not None:
            seen.setdefault(url)
    return list(seen)


def _decode(body: bytes, encoding: str | None) -> str | bytes:
    if encoding is None:
        return body
    try:
        text = body.decode(encoding, errors="replace")
    except LookupError:
        return body
    # lxml refuses str input that carries its own XML encoding declaration.
    return body if text.lstrip().startswith("<?xml") else text

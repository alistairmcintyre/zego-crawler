"""URL normalisation and scoping rules.

Every URL that enters the crawler passes through :func:`normalise_url` so that
trivially different spellings of the same resource (``HTTP://Example.com:80/#top``
vs ``http://example.com/``) are de-duplicated against a single canonical form.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit, urlunsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalise_url(url: str, base: str | None = None) -> str | None:
    """Return a canonical absolute form of ``url``, or ``None`` if it is not crawlable.

    - Relative URLs are resolved against ``base``.
    - ``http`` and ``https`` are accepted.
    - (``mailto:``, ``javascript:`` etc. are dropped).
    - Scheme and host are lower-cased; default ports are removed.
    - Fragments are removed, since they never change the document served.
    - An empty path becomes ``/``.
    - The query string is kept verbatim: it frequently identifies distinct content.
    """
    url = url.strip()
    if not url:
        return None
    if base is not None:
        url = urljoin(base, url)

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:  # e.g. an invalid port or malformed IPv6 literal
        return None

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES or not parts.hostname:
        return None

    host = parts.hostname.lower()
    if ":" in host:  # IPv6 literal needs its brackets back
        host = f"[{host}]"
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"

    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def host_of(url: str) -> str:
    """Return the ``host[:port]`` component of an already normalised URL."""
    return urlsplit(url).netloc


def is_same_host(url: str, host: str) -> bool:
    """Whether ``url`` lives on exactly ``host``.

    This is a strict comparison: subdomains (including ``www.``) are treated as
    different sites, as required by the brief.
    """
    return host_of(url) == host


def origin_of(url: str) -> str:
    """Return ``scheme://host[:port]`` for ``url`` (normalising it first)."""
    normalised = normalise_url(url)
    if normalised is None:
        raise ValueError(f"Not a valid http(s) URL: {url!r}")
    parts = urlsplit(normalised)
    return f"{parts.scheme}://{parts.netloc}"

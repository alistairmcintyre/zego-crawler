import pytest

from crawler.urls import host_of, is_same_host, normalise_url, origin_of, with_scheme


@pytest.mark.parametrize(
    ("url", "base", "expected"),
    [
        ("https://example.com", None, "https://example.com/"),
        ("HTTPS://Example.COM/Path", None, "https://example.com/Path"),
        ("http://example.com:80/a", None, "http://example.com/a"),
        ("https://example.com:443/a", None, "https://example.com/a"),
        ("https://example.com:8443/a", None, "https://example.com:8443/a"),
        ("https://example.com/a#section", None, "https://example.com/a"),
        ("https://example.com/a?b=1&c=2", None, "https://example.com/a?b=1&c=2"),
        ("  https://example.com/a  ", None, "https://example.com/a"),
        ("/about", "https://example.com/blog/post", "https://example.com/about"),
        ("next", "https://example.com/blog/post", "https://example.com/blog/next"),
        ("../up", "https://example.com/a/b/c", "https://example.com/a/up"),
        ("//cdn.example.com/x", "https://example.com/", "https://cdn.example.com/x"),
        ("?page=2", "https://example.com/list", "https://example.com/list?page=2"),
        ("#top", "https://example.com/page", "https://example.com/page"),
        ("http://[::1]:8080/x", None, "http://[::1]:8080/x"),
    ],
)
def test_normalise_url(url: str, base: str | None, expected: str) -> None:
    assert normalise_url(url, base) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "mailto:someone@example.com",
        "javascript:void(0)",
        "tel:+441234567890",
        "ftp://example.com/file",
        "data:text/html,hello",
        "https://",
        "http://example.com:notaport/",
        "relative/without/base",
    ],
)
def test_normalise_url_rejects_uncrawlable(url: str) -> None:
    assert normalise_url(url) is None


def test_host_of_includes_non_default_port() -> None:
    assert host_of("http://localhost:8000/x") == "localhost:8000"


@pytest.mark.parametrize(
    ("url", "same"),
    [
        ("https://example.com/anything", True),
        ("http://example.com/other-scheme", True),
        ("https://www.example.com/", False),
        ("https://blog.example.com/", False),
        ("https://example.co.uk/", False),
        ("https://example.com:8443/", False),
    ],
)
def test_is_same_host_is_strict(url: str, same: bool) -> None:
    assert is_same_host(url, "example.com") is same


def test_origin_of() -> None:
    assert origin_of("HTTPS://Example.com:443/a/b?c#d") == "https://example.com"
    assert origin_of("http://localhost:8000/x") == "http://localhost:8000"


def test_origin_of_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Not a valid"):
        origin_of("mailto:x@example.com")


def test_with_scheme() -> None:
    assert with_scheme("http://example.com/a?q=1", "https") == "https://example.com/a?q=1"

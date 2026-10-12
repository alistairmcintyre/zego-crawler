from crawler.parser import extract_links

PAGE = "https://example.com/blog/post"


def test_extracts_absolute_and_relative_links_in_document_order() -> None:
    body = b"""
    <html><body>
      <a href="/about">About</a>
      <a href="next">Next</a>
      <a href="https://other.com/x">External</a>
    </body></html>
    """
    assert extract_links(body, PAGE) == [
        "https://example.com/about",
        "https://example.com/blog/next",
        "https://other.com/x",
    ]


def test_deduplicates_after_normalisation() -> None:
    body = b'<a href="/a">1</a><a href="/a#x">2</a><a href="https://EXAMPLE.com/a">3</a>'
    assert extract_links(body, PAGE) == ["https://example.com/a"]


def test_ignores_non_http_links_and_anchors_without_href() -> None:
    body = b"""
    <a href="mailto:x@example.com">m</a>
    <a href="javascript:void(0)">j</a>
    <a name="anchor">no href</a>
    <a href="">empty</a>
    <a href="/ok">ok</a>
    """
    assert extract_links(body, PAGE) == ["https://example.com/ok"]


def test_honours_base_href() -> None:
    body = b'<html><head><base href="https://example.com/docs/"></head><a href="intro">i</a></html>'
    assert extract_links(body, PAGE) == ["https://example.com/docs/intro"]


def test_only_anchor_tags_are_links() -> None:
    body = b'<link href="/style.css"><img src="/img.png"><script src="/app.js"></script>'
    assert extract_links(body, PAGE) == []


def test_empty_or_whitespace_body() -> None:
    assert extract_links(b"", PAGE) == []
    assert extract_links(b"   \n ", PAGE) == []


def test_tolerates_malformed_html() -> None:
    body = b'<html><body><div><a href="/one">one<a href="/two">two</p></div>'
    assert extract_links(body, PAGE) == ["https://example.com/one", "https://example.com/two"]


def test_uses_declared_encoding() -> None:
    body = '<a href="/café">x</a>'.encode("latin-1")
    assert extract_links(body, PAGE, encoding="latin-1") == ["https://example.com/café"]


def test_unknown_encoding_falls_back_to_sniffing() -> None:
    assert extract_links(b'<a href="/x">x</a>', PAGE, encoding="not-a-codec") == [
        "https://example.com/x"
    ]


def test_xml_declaration_with_declared_encoding() -> None:
    body = b'<?xml version="1.0" encoding="utf-8"?><html><a href="/x">x</a></html>'
    assert extract_links(body, PAGE, encoding="utf-8") == ["https://example.com/x"]


def test_meta_charset_is_honoured_without_header() -> None:
    body = '<meta charset="iso-8859-1"><a href="/caf\u00e9">x</a>'.encode("latin-1")
    assert extract_links(body, PAGE) == ["https://example.com/caf\u00e9"]


def test_unparseable_document_returns_no_links() -> None:
    assert extract_links(b"<!-- only a comment -->", PAGE) == []

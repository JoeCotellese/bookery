# ABOUTME: Unit tests for the Google Books metadata provider.
# ABOUTME: Mocks HTTP client; verifies ISBN and title/author parsing.

from typing import Any

import pytest

from bookery.metadata.googlebooks import GoogleBooksProvider
from bookery.metadata.http import MetadataFetchError


class FakeHttpClient:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self._responses = responses or {}
        self.last_params: dict[str, str] | None = None
        self.request_log: list[tuple[str, dict[str, str] | None]] = []

    def get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        self.last_params = params
        self.request_log.append((url, params))
        for pattern, response in self._responses.items():
            if pattern in url or (params and pattern in (params.get("q") or "")):
                if isinstance(response, Exception):
                    raise response
                return response
        return {"items": []}


def _volume(
    *,
    vol_id: str = "VOL1",
    title: str = "Dune",
    subtitle: str | None = None,
    authors: list[str] | None = None,
    isbn_13: str | None = "9780441013593",
    page_count: int | None = 412,
    language: str = "en",
    publisher: str | None = "Chilton",
    published_date: str | None = "1965",
    description: str | None = "<p>Epic.</p>",
    categories: list[str] | None = None,
    thumbnail: str | None = "http://books.google.com/cover.jpg",
) -> dict[str, Any]:
    info: dict[str, Any] = {
        "title": title,
        "authors": authors if authors is not None else ["Frank Herbert"],
        "language": language,
    }
    if subtitle:
        info["subtitle"] = subtitle
    if publisher:
        info["publisher"] = publisher
    if published_date:
        info["publishedDate"] = published_date
    if page_count is not None:
        info["pageCount"] = page_count
    if description is not None:
        info["description"] = description
    if categories:
        info["categories"] = categories
    if isbn_13:
        info["industryIdentifiers"] = [{"type": "ISBN_13", "identifier": isbn_13}]
    if thumbnail:
        info["imageLinks"] = {"thumbnail": thumbnail}
    return {"id": vol_id, "volumeInfo": info}


def test_search_by_isbn_returns_parsed_candidate() -> None:
    http = FakeHttpClient({"volumes": {"items": [_volume()]}})
    provider = GoogleBooksProvider(http_client=http)

    candidates = provider.search_by_isbn("978-0-441-01359-3")

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.source == "googlebooks"
    assert cand.source_id == "VOL1"
    assert cand.confidence == 1.0
    assert cand.metadata.title == "Dune"
    assert cand.metadata.authors == ["Frank Herbert"]
    assert cand.metadata.isbn == "9780441013593"
    assert cand.metadata.page_count == 412
    assert cand.metadata.published_date == "1965"
    assert cand.metadata.publisher == "Chilton"
    assert cand.metadata.cover_url == "https://books.google.com/cover.jpg"
    assert cand.metadata.description == "Epic."
    assert cand.metadata.identifiers["googlebooks_volume"] == "VOL1"
    assert http.last_params == {"q": "isbn:9780441013593"}


def test_search_by_isbn_with_no_items_returns_empty() -> None:
    http = FakeHttpClient({"volumes": {"items": []}})
    provider = GoogleBooksProvider(http_client=http)
    assert provider.search_by_isbn("9780000000000") == []


def test_search_by_isbn_on_fetch_error_returns_empty() -> None:
    http = FakeHttpClient({"volumes": MetadataFetchError("boom")})
    provider = GoogleBooksProvider(http_client=http)
    assert provider.search_by_isbn("9780000000000") == []


def test_search_by_title_author_builds_query_and_sorts() -> None:
    http = FakeHttpClient(
        {
            "volumes": {
                "items": [
                    _volume(vol_id="A", title="Completely Unrelated"),
                    _volume(vol_id="B", title="Dune"),
                ]
            }
        }
    )
    provider = GoogleBooksProvider(http_client=http)

    candidates = provider.search_by_title_author("Dune", "Frank Herbert")

    assert len(candidates) == 2
    # The exact-match candidate should rank first.
    assert candidates[0].source_id == "B"
    assert http.last_params == {
        "q": "intitle:Dune inauthor:Frank Herbert",
        "maxResults": "5",
    }


def test_subtitle_is_kept_separate_from_title() -> None:
    http = FakeHttpClient(
        {"volumes": {"items": [_volume(title="Dune", subtitle="A Novel")]}}
    )
    provider = GoogleBooksProvider(http_client=http)
    candidates = provider.search_by_isbn("9780441013593")
    assert candidates[0].metadata.title == "Dune"
    assert candidates[0].metadata.subtitle == "A Novel"


def test_parses_rating_ratings_count_print_type_and_maturity() -> None:
    vol = _volume(title="Dune")
    vol["volumeInfo"]["averageRating"] = 4.3
    vol["volumeInfo"]["ratingsCount"] = 2145
    vol["volumeInfo"]["printType"] = "BOOK"
    vol["volumeInfo"]["maturityRating"] = "NOT_MATURE"
    http = FakeHttpClient({"volumes": {"items": [vol]}})
    provider = GoogleBooksProvider(http_client=http)
    meta = provider.search_by_isbn("9780441013593")[0].metadata
    assert meta.rating == 4.3
    assert meta.ratings_count == 2145
    assert meta.print_type == "BOOK"
    assert meta.maturity_rating == "NOT_MATURE"


def test_largest_cover_variant_is_selected() -> None:
    vol = _volume(title="Dune")
    vol["volumeInfo"]["imageLinks"] = {
        "smallThumbnail": "http://example/st.jpg",
        "thumbnail": "http://example/t.jpg",
        "small": "http://example/s.jpg",
        "medium": "http://example/m.jpg",
        "large": "http://example/l.jpg",
        "extraLarge": "http://example/xl.jpg",
    }
    http = FakeHttpClient({"volumes": {"items": [vol]}})
    provider = GoogleBooksProvider(http_client=http)
    meta = provider.search_by_isbn("9780441013593")[0].metadata
    assert meta.cover_url == "https://example/xl.jpg"


def test_cover_falls_back_to_next_available_variant() -> None:
    vol = _volume(title="Dune", thumbnail=None)
    vol["volumeInfo"]["imageLinks"] = {"medium": "http://example/m.jpg"}
    http = FakeHttpClient({"volumes": {"items": [vol]}})
    provider = GoogleBooksProvider(http_client=http)
    meta = provider.search_by_isbn("9780441013593")[0].metadata
    assert meta.cover_url == "https://example/m.jpg"


def test_preview_and_info_links_recorded_in_identifiers() -> None:
    vol = _volume(title="Dune")
    vol["volumeInfo"]["previewLink"] = "https://books.google.com/preview"
    vol["volumeInfo"]["infoLink"] = "https://books.google.com/info"
    http = FakeHttpClient({"volumes": {"items": [vol]}})
    provider = GoogleBooksProvider(http_client=http)
    meta = provider.search_by_isbn("9780441013593")[0].metadata
    assert meta.identifiers["googlebooks_preview"] == "https://books.google.com/preview"
    assert meta.identifiers["googlebooks_info"] == "https://books.google.com/info"


def test_non_book_print_type_is_skipped() -> None:
    mag = _volume(vol_id="MAG", title="Magazine")
    mag["volumeInfo"]["printType"] = "MAGAZINE"
    book = _volume(vol_id="BOOKVOL", title="Dune")
    book["volumeInfo"]["printType"] = "BOOK"
    http = FakeHttpClient({"volumes": {"items": [mag, book]}})
    provider = GoogleBooksProvider(http_client=http)
    candidates = provider.search_by_title_author("Dune")
    titles = [c.metadata.title for c in candidates]
    assert "Magazine" not in titles
    assert "Dune" in titles


def test_isbn_10_is_used_when_no_isbn_13() -> None:
    volume = _volume(isbn_13=None)
    volume["volumeInfo"]["industryIdentifiers"] = [
        {"type": "ISBN_10", "identifier": "0441013597"}
    ]
    http = FakeHttpClient({"volumes": {"items": [volume]}})
    provider = GoogleBooksProvider(http_client=http)
    candidates = provider.search_by_isbn("0441013597")
    assert candidates[0].metadata.isbn == "0441013597"


def test_lookup_by_url_parses_volume_id() -> None:
    http = FakeHttpClient({"/VOL42": _volume(vol_id="VOL42")})
    provider = GoogleBooksProvider(http_client=http)
    cand = provider.lookup_by_url("https://books.google.com/books?id=VOL42")
    assert cand is not None
    assert cand.source_id == "VOL42"


def test_lookup_by_url_returns_none_for_bad_url() -> None:
    http = FakeHttpClient({})
    provider = GoogleBooksProvider(http_client=http)
    assert provider.lookup_by_url("https://example.com/nope") is None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://books.google.com/books?id=ABC_123", "ABC_123"),
        ("https://www.google.com/books/edition/_/ABCxyz", "ABCxyz"),
        ("https://example.com/no-id", None),
    ],
)
def test_parse_volume_id(url: str, expected: str | None) -> None:
    assert GoogleBooksProvider._parse_volume_id(url) == expected


def test_page_count_of_zero_is_coerced_to_none() -> None:
    # Google Books frequently returns pageCount: 0 for books without an
    # authoritative count. That should not pollute the BookMetadata.
    http = FakeHttpClient({"volumes": {"items": [_volume(page_count=0)]}})
    provider = GoogleBooksProvider(http_client=http)
    candidates = provider.search_by_isbn("9780441013593")
    assert candidates[0].metadata.page_count is None

# ABOUTME: Unit tests for the Hardcover metadata provider.
# ABOUTME: Mocks the GraphQL POST client; verifies ISBN/title lookups and series mapping.

import logging
from typing import Any

from bookery.metadata.hardcover import _HC_ENDPOINT, HardcoverProvider
from bookery.metadata.http import MetadataFetchError


class FakePostClient:
    """Records post_json calls and replays canned responses in order."""

    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any], dict[str, str] | None]] = []

    def post_json(
        self,
        url: str,
        json_body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((url, json_body, headers))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _book(
    *,
    book_id: int = 101,
    title: str = "The Eye of the World",
    series_name: str | None = "The Wheel of Time",
    position: float | None = 1,
) -> dict[str, Any]:
    book: dict[str, Any] = {
        "id": book_id,
        "title": title,
        "subtitle": None,
        "description": "The Wheel of Time turns.",
        "rating": 4.21,
        "ratings_count": 5432,
        "cached_image": {"url": "https://assets.hardcover.app/covers/101.jpg"},
        "slug": "the-eye-of-the-world",
        "contributions": [
            {"author": {"name": "Robert Jordan"}, "contribution": None},
            {"author": {"name": "Michael Kramer"}, "contribution": "Narrator"},
        ],
        "featured_book_series": None,
    }
    if series_name is not None:
        book["featured_book_series"] = {
            "position": position,
            "series": {"name": series_name},
        }
    return book


def _edition(**overrides: Any) -> dict[str, Any]:
    edition = {
        "isbn_13": "9780312850098",
        "isbn_10": "0312850093",
        "pages": 782,
        "release_date": "1990-01-15",
        "publisher": {"name": "Tor Books"},
    }
    edition.update(overrides)
    return edition


def _isbn_response(book: dict[str, Any]) -> dict[str, Any]:
    return {"data": {"editions": [{**_edition(), "book": book}]}}


class TestSearchByIsbn:
    def test_maps_series_and_core_fields(self) -> None:
        http = FakePostClient([_isbn_response(_book())])
        provider = HardcoverProvider(http_client=http, token="tok")

        candidates = provider.search_by_isbn("978-0-312-85009-8")

        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.source == "hardcover"
        assert cand.confidence == 1.0
        meta = cand.metadata
        assert meta.title == "The Eye of the World"
        assert meta.series == "The Wheel of Time"
        assert meta.series_index == 1.0
        assert meta.rating == 4.21
        assert meta.ratings_count == 5432
        # Narrator contribution filtered out; primary (None) kept.
        assert meta.authors == ["Robert Jordan"]
        assert meta.isbn == "9780312850098"
        assert meta.publisher == "Tor Books"
        assert meta.page_count == 782
        assert meta.published_date == "1990-01-15"
        assert meta.cover_url == "https://assets.hardcover.app/covers/101.jpg"
        assert meta.identifiers["hardcover_book"] == "101"
        assert meta.identifiers["hardcover_slug"] == "the-eye-of-the-world"

    def test_sends_bearer_token_and_normalized_isbn(self) -> None:
        http = FakePostClient([_isbn_response(_book())])
        provider = HardcoverProvider(http_client=http, token="tok")

        provider.search_by_isbn("978-0-312-85009-8")

        url, body, headers = http.calls[0]
        assert url == _HC_ENDPOINT
        assert headers is not None
        assert headers["Authorization"] == "Bearer tok"
        assert body["variables"]["isbn"] == "9780312850098"

    def test_book_without_series_maps_none(self) -> None:
        http = FakePostClient([_isbn_response(_book(series_name=None))])
        provider = HardcoverProvider(http_client=http, token="tok")

        meta = provider.search_by_isbn("9780312850098")[0].metadata

        assert meta.series is None
        assert meta.series_index is None

    def test_no_editions_returns_empty(self) -> None:
        http = FakePostClient([{"data": {"editions": []}}])
        provider = HardcoverProvider(http_client=http, token="tok")

        assert provider.search_by_isbn("9780312850098") == []


class TestSearchByTitleAuthor:
    def test_two_round_trips_and_scoring(self) -> None:
        search_response = {"data": {"search": {"ids": [101, 202]}}}
        books_response = {
            "data": {
                "books": [
                    {**_book(), "editions": [_edition()]},
                    {
                        **_book(
                            book_id=202,
                            title="Completely Unrelated Title",
                            series_name=None,
                        ),
                        "editions": [_edition(isbn_13="9780000000000")],
                    },
                ]
            }
        }
        http = FakePostClient([search_response, books_response])
        provider = HardcoverProvider(http_client=http, token="tok")

        candidates = provider.search_by_title_author("The Eye of the World", "Robert Jordan")

        assert len(http.calls) == 2
        assert http.calls[0][1]["variables"]["query"] == "The Eye of the World Robert Jordan"
        assert http.calls[1][1]["variables"]["ids"] == [101, 202]
        assert len(candidates) == 2
        # Exact title match must outrank the unrelated one.
        assert candidates[0].metadata.title == "The Eye of the World"
        assert candidates[0].confidence > candidates[1].confidence
        assert candidates[0].metadata.series == "The Wheel of Time"

    def test_no_ids_returns_empty_without_second_call(self) -> None:
        http = FakePostClient([{"data": {"search": {"ids": []}}}])
        provider = HardcoverProvider(http_client=http, token="tok")

        assert provider.search_by_title_author("Nope") == []
        assert len(http.calls) == 1


class TestFailureModes:
    def test_missing_token_disables_provider(self, caplog: Any) -> None:
        http = FakePostClient([])
        provider = HardcoverProvider(http_client=http, token=None)

        with caplog.at_level(logging.WARNING):
            assert provider.search_by_isbn("9780312850098") == []
            assert provider.search_by_title_author("The Eye of the World") == []

        assert len(http.calls) == 0
        assert any("HARDCOVER_API_KEY" in r.message for r in caplog.records)

    def test_graphql_errors_return_empty(self, caplog: Any) -> None:
        http = FakePostClient([{"errors": [{"message": "field 'x' not found"}]}])
        provider = HardcoverProvider(http_client=http, token="tok")

        with caplog.at_level(logging.WARNING):
            assert provider.search_by_isbn("9780312850098") == []

        assert any("field 'x' not found" in r.message for r in caplog.records)

    def test_fetch_error_returns_empty(self, caplog: Any) -> None:
        http = FakePostClient([MetadataFetchError("HTTP 429 after 4 attempts")])
        provider = HardcoverProvider(http_client=http, token="tok")

        with caplog.at_level(logging.WARNING):
            assert provider.search_by_isbn("9780312850098") == []

        assert any("429" in r.message for r in caplog.records)

    def test_lookup_by_url_unsupported(self) -> None:
        provider = HardcoverProvider(http_client=FakePostClient([]), token="tok")
        assert provider.lookup_by_url("https://hardcover.app/books/the-eye-of-the-world") is None


def test_provider_name() -> None:
    assert HardcoverProvider(http_client=FakePostClient([]), token="tok").name == "hardcover"


def test_satisfies_metadata_provider_protocol() -> None:
    from bookery.metadata.provider import MetadataProvider

    provider = HardcoverProvider(http_client=FakePostClient([]), token="tok")
    assert isinstance(provider, MetadataProvider)

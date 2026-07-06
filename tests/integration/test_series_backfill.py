# ABOUTME: Integration tests for the series backfill flow (issue #151 test matrix).
# ABOUTME: Real GB/HC provider parsing through ConsensusProvider and the backfill CLI.

from pathlib import Path
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.consensus import ConsensusProvider
from bookery.metadata.googlebooks import GoogleBooksProvider
from bookery.metadata.hardcover import HardcoverProvider
from bookery.metadata.http import MetadataFetchError
from bookery.metadata.types import BookMetadata

_EOTW_ISBN = "9780312850098"


class FakeGetClient:
    """GET stub for GoogleBooksProvider: every request returns the canned payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        return self._payload


class FakePostClient:
    """POST stub for HardcoverProvider: replays responses in order."""

    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self._responses = list(responses)

    def post_json(
        self,
        url: str,
        json_body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _gb_volume(*, series_info: dict[str, Any] | None = None) -> dict[str, Any]:
    info: dict[str, Any] = {
        "title": "The Eye of the World",
        "authors": ["Robert Jordan"],
        "language": "en",
        "industryIdentifiers": [{"type": "ISBN_13", "identifier": _EOTW_ISBN}],
    }
    if series_info is not None:
        info["seriesInfo"] = series_info
    return {"items": [{"id": "GBVOL1", "volumeInfo": info, "kind": "books#volume"}]}


def _hc_isbn_response(*, series: bool = True) -> dict[str, Any]:
    book: dict[str, Any] = {
        "id": 101,
        "title": "The Eye of the World",
        "rating": 4.21,
        "ratings_count": 5432,
        "slug": "the-eye-of-the-world",
        "contributions": [{"author": {"name": "Robert Jordan"}, "contribution": None}],
        "featured_book_series": (
            {"position": 1, "series": {"name": "The Wheel of Time"}} if series else None
        ),
    }
    return {
        "data": {
            "editions": [
                {
                    "isbn_13": _EOTW_ISBN,
                    "isbn_10": None,
                    "pages": 782,
                    "release_date": "1990-01-15",
                    "publisher": {"name": "Tor Books"},
                    "book": book,
                }
            ]
        }
    }


def _add_book(db_path: Path, title: str, *, isbn: str | None = None) -> int:
    conn = open_library(db_path)
    book_id = LibraryCatalog(conn).add_book(
        BookMetadata(
            title=title,
            authors=["Robert Jordan"],
            isbn=isbn,
            source_path=Path(f"/books/{title}.epub"),
        ),
        file_hash=f"hash-{title}-{isbn}",
    )
    conn.close()
    return book_id


def _catalog_row(db_path: Path, book_id: int) -> dict[str, Any]:
    conn = open_library(db_path)
    row = conn.execute(
        "SELECT series, series_index FROM books WHERE id = ?", (book_id,)
    ).fetchone()
    provenance = {
        name: entry.source for name, entry in LibraryCatalog(conn).get_provenance(book_id).items()
    }
    conn.close()
    return {
        "series": row["series"],
        "series_index": row["series_index"],
        "provenance": provenance,
    }


class TestConsensusMergesSeriesInfo:
    """Matrix rows: GB seriesInfo shapes survive the consensus merge."""

    def test_gb_volume_series_shape_yields_index_and_stashed_series_id(self) -> None:
        gb = GoogleBooksProvider(
            http_client=FakeGetClient(
                _gb_volume(
                    series_info={
                        "bookDisplayNumber": "1",
                        "volumeSeries": [{"seriesId": "gb-wot", "orderNumber": 1}],
                    }
                )
            )
        )
        consensus = ConsensusProvider([gb])

        merged = consensus.search_by_isbn(_EOTW_ISBN)[0].metadata

        assert merged.series_index == 1.0
        assert merged.identifiers["googlebooks_series"] == "gb-wot"

    def test_gb_display_number_only_shape(self) -> None:
        gb = GoogleBooksProvider(
            http_client=FakeGetClient(_gb_volume(series_info={"bookDisplayNumber": "2"}))
        )
        consensus = ConsensusProvider([gb])

        merged = consensus.search_by_isbn(_EOTW_ISBN)[0].metadata

        assert merged.series_index == 2.0

    def test_gb_index_and_hc_name_merge_independently(self) -> None:
        gb = GoogleBooksProvider(
            http_client=FakeGetClient(_gb_volume(series_info={"bookDisplayNumber": "1"}))
        )
        hc = HardcoverProvider(http_client=FakePostClient([_hc_isbn_response()]), token="tok")
        consensus = ConsensusProvider([gb, hc])

        merged = consensus.search_by_isbn(_EOTW_ISBN)[0].metadata

        assert merged.series == "The Wheel of Time"
        assert merged.series_index == 1.0
        assert merged.rating == 4.21
        assert merged.identifiers["provenance_series"] == "hardcover"


class TestBackfillEndToEnd:
    """Matrix rows: catalog rows actually gain series data via the CLI."""

    def _run_backfill(self, db_path: Path, provider: Any, *args: str) -> Any:
        with patch(
            "bookery.cli.commands.series_cmd._create_provider",
            return_value=provider,
        ):
            return CliRunner().invoke(cli, ["series", "backfill", *args, "--db", str(db_path)])

    def test_hardcover_isbn_lookup_fills_catalog_row(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "The Eye of the World", isbn=_EOTW_ISBN)
        gb = GoogleBooksProvider(http_client=FakeGetClient({"items": []}))
        hc = HardcoverProvider(http_client=FakePostClient([_hc_isbn_response()]), token="tok")
        provider = ConsensusProvider([gb, hc])

        result = self._run_backfill(db_path, provider, str(book_id))

        assert result.exit_code == 0
        row = _catalog_row(db_path, book_id)
        assert row["series"] == "The Wheel of Time"
        assert row["series_index"] == 1.0
        assert row["provenance"]["series"] == "hardcover"

    def test_hardcover_rate_limit_is_clean_skip(self, tmp_path: Path) -> None:
        """Exhausted 429 retries surface as a warning, not a crash; book stays unresolved."""
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "The Eye of the World", isbn=_EOTW_ISBN)
        gb = GoogleBooksProvider(http_client=FakeGetClient({"items": []}))
        hc = HardcoverProvider(
            http_client=FakePostClient(
                [
                    MetadataFetchError("HTTP 429 after 4 attempts"),
                    MetadataFetchError("HTTP 429 after 4 attempts"),
                ]
            ),
            token="tok",
        )
        provider = ConsensusProvider([gb, hc])

        result = self._run_backfill(db_path, provider, str(book_id))

        assert result.exit_code == 0
        assert _catalog_row(db_path, book_id)["series"] is None
        assert "unresolved" in result.output

    def test_heuristic_title_fills_when_providers_empty(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "Foo (Riftwar Saga #2)")
        gb = GoogleBooksProvider(http_client=FakeGetClient({"items": []}))
        # No ISBN on the book: the flow goes straight to title/author search.
        hc = HardcoverProvider(
            http_client=FakePostClient([{"data": {"search": {"ids": []}}}]),
            token="tok",
        )
        provider = ConsensusProvider([gb, hc])

        result = self._run_backfill(db_path, provider, str(book_id))

        assert result.exit_code == 0
        row = _catalog_row(db_path, book_id)
        assert row["series"] == "Riftwar Saga"
        assert row["series_index"] == 2.0
        assert row["provenance"]["series"] == "heuristic"

# ABOUTME: Unit tests for BookMetadata's published_date, page_count, and cover_url.
# ABOUTME: Covers dataclass defaults, DB round-trip, and OL parser population.

from pathlib import Path

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.openlibrary_parser import (
    parse_isbn_response,
    parse_search_results,
    parse_works_metadata,
)
from bookery.metadata.types import BookMetadata


class TestBookMetadataDefaults:
    def test_new_fields_default_to_none(self) -> None:
        meta = BookMetadata(title="T")
        assert meta.published_date is None
        assert meta.original_publication_date is None
        assert meta.page_count is None
        assert meta.cover_url is None


class TestCatalogRoundTrip:
    def test_new_fields_survive_insert_and_read(self, tmp_path: Path) -> None:
        conn = open_library(tmp_path / "lib.db")
        try:
            catalog = LibraryCatalog(conn)
            meta = BookMetadata(
                title="T",
                authors=["A"],
                isbn="9780151446476",
                source_path=Path("/tmp/x.epub"),
                published_date="2010-05",
                original_publication_date="2010",
                page_count=321,
                cover_url="https://covers.openlibrary.org/b/id/99-L.jpg",
            )
            book_id = catalog.add_book(meta, file_hash="h" * 64)

            record = catalog.get_by_id(book_id)
            assert record is not None
            assert record.metadata.published_date == "2010-05"
            assert record.metadata.original_publication_date == "2010"
            assert record.metadata.page_count == 321
            assert record.metadata.cover_url == "https://covers.openlibrary.org/b/id/99-L.jpg"
        finally:
            conn.close()


class TestOpenLibraryParserPopulation:
    def test_isbn_response_populates_published_date_and_pages(self) -> None:
        data = {
            "title": "T",
            "publish_date": "August 2010",
            "number_of_pages": 321,
            "covers": [42],
        }
        meta = parse_isbn_response(data)
        assert meta.published_date == "August 2010"
        assert meta.page_count == 321
        assert meta.cover_url == "https://covers.openlibrary.org/b/id/42-L.jpg"

    def test_isbn_response_falls_back_to_isbn_cover_when_no_covers(self) -> None:
        data = {"title": "T", "isbn_13": ["9780151446476"]}
        meta = parse_isbn_response(data)
        assert meta.cover_url is not None
        assert "9780151446476" in meta.cover_url

    def test_works_metadata_populates_first_publish_date(self) -> None:
        data = {
            "key": "/works/OL1W",
            "title": "T",
            "first_publish_date": "1949",
        }
        meta = parse_works_metadata(data)
        assert meta.original_publication_date == "1949"

    def test_works_metadata_preserves_openlibrary_author_keys(self) -> None:
        data = {
            "key": "/works/OL1W",
            "title": "T",
            "authors": [{"author": {"key": "/authors/OL1A"}}],
        }
        meta = parse_works_metadata(data)
        assert meta.identifiers["openlibrary_author_keys"] == "/authors/OL1A"

    def test_search_result_populates_cover_and_first_year(self) -> None:
        data = {
            "docs": [
                {
                    "title": "T",
                    "cover_i": 77,
                    "first_publish_year": 1984,
                    "number_of_pages_median": 250,
                    "author_key": ["OL1A"],
                }
            ]
        }
        results = parse_search_results(data)
        assert len(results) == 1
        assert results[0].cover_url == "https://covers.openlibrary.org/b/id/77-L.jpg"
        assert results[0].original_publication_date == "1984"
        assert results[0].page_count == 250
        assert results[0].identifiers["openlibrary_author_keys"] == "/authors/OL1A"

    def test_cover_url_skips_sentinel_cover_ids(self) -> None:
        data = {"title": "T", "covers": [-1, 88]}
        meta = parse_isbn_response(data)
        assert meta.cover_url == "https://covers.openlibrary.org/b/id/88-L.jpg"

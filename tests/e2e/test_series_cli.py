# ABOUTME: End-to-end tests for the `bookery series` CLI group.
# ABOUTME: Covers `series ls` coverage listing and `series backfill` provider/heuristic fills.

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.mapping import BookRecord
from bookery.formats.epub import read_calibre_series
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata


class FakeProvider:
    """Provider stub returning canned candidates keyed by isbn or title."""

    name = "hardcover"

    def __init__(self, candidates: dict[str, MetadataCandidate] | None = None) -> None:
        self._candidates = candidates or {}
        self.isbn_calls: list[str] = []
        self.title_calls: list[tuple[str, str | None]] = []

    def search_by_isbn(self, isbn: str) -> list[MetadataCandidate]:
        self.isbn_calls.append(isbn)
        cand = self._candidates.get(isbn)
        return [cand] if cand else []

    def search_by_title_author(
        self, title: str, author: str | None = None
    ) -> list[MetadataCandidate]:
        self.title_calls.append((title, author))
        cand = self._candidates.get(title)
        return [cand] if cand else []

    def lookup_by_url(self, url: str) -> MetadataCandidate | None:
        return None


def _cand(series: str, series_index: float | None, confidence: float = 1.0) -> MetadataCandidate:
    return MetadataCandidate(
        metadata=BookMetadata(
            title="The Eye of the World",
            authors=["Robert Jordan"],
            series=series,
            series_index=series_index,
        ),
        confidence=confidence,
        source="hardcover",
        source_id="hc:101",
    )


def _add_book(
    db_path: Path,
    title: str,
    *,
    authors: list[str] | None = None,
    isbn: str | None = None,
    series: str | None = None,
    series_index: float | None = None,
    file_hash: str = "",
    output: Path | None = None,
) -> int:
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    book_id = catalog.add_book(
        BookMetadata(
            title=title,
            authors=authors or ["Robert Jordan"],
            isbn=isbn,
            series=series,
            series_index=series_index,
            source_path=Path(f"/books/{title}.epub"),
        ),
        file_hash=file_hash or f"hash-{title}",
        output_path=output,
    )
    conn.close()
    return book_id


def _make_epub(path: Path, title: str) -> None:
    """Write a minimal library EPUB carrying no series meta (the stale state)."""
    book = epub.EpubBook()
    book.set_identifier(f"id-{title}")
    book.set_title(title)
    book.set_language("en")
    book.add_author("Robert Jordan")
    chapter = epub.EpubHtml(title="c", file_name="c.xhtml", lang="en")
    chapter.content = b"<html><body><p>x</p></body></html>"
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)


def _get_book(db_path: Path, book_id: int) -> BookRecord:
    conn = open_library(db_path)
    record = LibraryCatalog(conn).get_by_id(book_id)
    conn.close()
    assert record is not None
    return record


class TestSeriesLs:
    def test_lists_series_with_counts_and_gaps(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        _add_book(db_path, "Book 1", series="Wheel of Time", series_index=1.0)
        _add_book(db_path, "Book 2", series="Wheel of Time")
        _add_book(db_path, "Solo", series="Cotton Malone", series_index=4.0)
        _add_book(db_path, "No Series")

        result = CliRunner().invoke(cli, ["series", "ls", "--db", str(db_path)])

        assert result.exit_code == 0
        assert "Wheel of Time" in result.output
        assert "Cotton Malone" in result.output
        assert "No Series" not in result.output

    def test_empty_catalog_message(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        _add_book(db_path, "No Series")

        result = CliRunner().invoke(cli, ["series", "ls", "--db", str(db_path)])

        assert result.exit_code == 0
        assert "No series" in result.output


class TestBackfillValidation:
    def test_requires_exactly_one_selector(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        runner = CliRunner()

        result = runner.invoke(cli, ["series", "backfill", "--db", str(db_path)])
        assert result.exit_code != 0
        assert "Specify exactly one" in result.output

        result = runner.invoke(cli, ["series", "backfill", "1", "--all", "--db", str(db_path)])
        assert result.exit_code != 0
        assert "Specify exactly one" in result.output


class TestBackfillProviderFill:
    def test_fills_series_from_provider_by_isbn(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "The Eye of the World", isbn="9780312850098")
        provider = FakeProvider({"9780312850098": _cand("The Wheel of Time", 1.0)})

        with patch("bookery.cli.commands.series_cmd._create_provider", return_value=provider):
            result = CliRunner().invoke(
                cli, ["series", "backfill", str(book_id), "--db", str(db_path)]
            )

        assert result.exit_code == 0
        record = _get_book(db_path, book_id)
        assert record.metadata.series == "The Wheel of Time"
        assert record.metadata.series_index == 1.0

        conn = open_library(db_path)
        provenance = LibraryCatalog(conn).get_provenance(book_id)
        conn.close()
        assert provenance["series"].source == "hardcover"

    def test_falls_back_to_title_author_search(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "The Eye of the World")  # no isbn
        provider = FakeProvider({"The Eye of the World": _cand("The Wheel of Time", 1.0)})

        with patch("bookery.cli.commands.series_cmd._create_provider", return_value=provider):
            result = CliRunner().invoke(
                cli, ["series", "backfill", str(book_id), "--db", str(db_path)]
            )

        assert result.exit_code == 0
        assert provider.title_calls == [("The Eye of the World", "Robert Jordan")]
        assert _get_book(db_path, book_id).metadata.series == "The Wheel of Time"

    def test_low_confidence_candidate_not_applied(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "The Eye of the World")
        provider = FakeProvider(
            {"The Eye of the World": _cand("Wrong Series", 9.0, confidence=0.2)}
        )

        with patch("bookery.cli.commands.series_cmd._create_provider", return_value=provider):
            result = CliRunner().invoke(
                cli, ["series", "backfill", str(book_id), "--db", str(db_path)]
            )

        assert result.exit_code == 0
        assert _get_book(db_path, book_id).metadata.series is None

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "The Eye of the World", isbn="9780312850098")
        provider = FakeProvider({"9780312850098": _cand("The Wheel of Time", 1.0)})

        with patch("bookery.cli.commands.series_cmd._create_provider", return_value=provider):
            result = CliRunner().invoke(
                cli,
                ["series", "backfill", str(book_id), "--dry-run", "--db", str(db_path)],
            )

        assert result.exit_code == 0
        assert "The Wheel of Time" in result.output
        assert _get_book(db_path, book_id).metadata.series is None

    def test_book_with_series_is_skipped(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(
            db_path, "The Eye of the World", series="Already Set", series_index=2.0
        )
        provider = FakeProvider()

        with patch("bookery.cli.commands.series_cmd._create_provider", return_value=provider):
            result = CliRunner().invoke(
                cli, ["series", "backfill", str(book_id), "--db", str(db_path)]
            )

        assert result.exit_code == 0
        assert provider.isbn_calls == []
        assert provider.title_calls == []
        record = _get_book(db_path, book_id)
        assert record.metadata.series == "Already Set"

    def test_all_selector_processes_only_books_missing_series(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        missing_id = _add_book(db_path, "The Eye of the World", isbn="9780312850098")
        _add_book(db_path, "Done Book", series="Done", series_index=1.0)
        provider = FakeProvider({"9780312850098": _cand("The Wheel of Time", 1.0)})

        with patch("bookery.cli.commands.series_cmd._create_provider", return_value=provider):
            result = CliRunner().invoke(cli, ["series", "backfill", "--all", "--db", str(db_path)])

        assert result.exit_code == 0
        assert _get_book(db_path, missing_id).metadata.series == "The Wheel of Time"
        assert len(provider.isbn_calls) == 1


class TestBackfillHeuristicFallback:
    def test_heuristic_fills_when_provider_misses(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "Foo (Series #3)")
        provider = FakeProvider()  # returns nothing

        with patch("bookery.cli.commands.series_cmd._create_provider", return_value=provider):
            result = CliRunner().invoke(
                cli, ["series", "backfill", str(book_id), "--db", str(db_path)]
            )

        assert result.exit_code == 0
        record = _get_book(db_path, book_id)
        assert record.metadata.series == "Series"
        assert record.metadata.series_index == 3.0

        conn = open_library(db_path)
        provenance = LibraryCatalog(conn).get_provenance(book_id)
        conn.close()
        assert provenance["series"].source == "heuristic"


class TestBackfillWritesEpubs:
    """The write phase pushes catalog series into the library EPUB files (#298)."""

    def test_fill_writes_series_into_epub_and_updates_hash(self, tmp_path: Path) -> None:
        epub_path = tmp_path / "eye.epub"
        _make_epub(epub_path, "The Eye of the World")
        db_path = tmp_path / "test.db"
        book_id = _add_book(
            db_path, "The Eye of the World", isbn="9780312850098", output=epub_path
        )
        provider = FakeProvider({"9780312850098": _cand("The Wheel of Time", 1.0)})

        with patch("bookery.cli.commands.series_cmd._create_provider", return_value=provider):
            result = CliRunner().invoke(
                cli, ["series", "backfill", str(book_id), "--db", str(db_path)]
            )

        assert result.exit_code == 0, result.output
        assert read_calibre_series(epub_path) == ("The Wheel of Time", 1.0)
        record = _get_book(db_path, book_id)
        assert record.file_hash != "hash-The Eye of the World"

    def test_stale_epub_rewritten_without_provider_call(self, tmp_path: Path) -> None:
        """A book whose catalog already has a series still gets its EPUB repaired."""
        epub_path = tmp_path / "eye.epub"
        _make_epub(epub_path, "The Eye of the World")
        db_path = tmp_path / "test.db"
        book_id = _add_book(
            db_path,
            "The Eye of the World",
            series="Already Set",
            series_index=2.0,
            output=epub_path,
        )
        provider = FakeProvider()

        with patch("bookery.cli.commands.series_cmd._create_provider", return_value=provider):
            result = CliRunner().invoke(
                cli, ["series", "backfill", str(book_id), "--db", str(db_path)]
            )

        assert result.exit_code == 0, result.output
        assert provider.isbn_calls == []
        assert provider.title_calls == []
        assert read_calibre_series(epub_path) == ("Already Set", 2.0)

    def test_second_run_is_noop(self, tmp_path: Path) -> None:
        epub_path = tmp_path / "eye.epub"
        _make_epub(epub_path, "The Eye of the World")
        db_path = tmp_path / "test.db"
        _add_book(
            db_path,
            "The Eye of the World",
            series="Already Set",
            series_index=2.0,
            output=epub_path,
        )
        runner = CliRunner()

        with patch(
            "bookery.cli.commands.series_cmd._create_provider", return_value=FakeProvider()
        ):
            runner.invoke(cli, ["series", "backfill", "--all", "--db", str(db_path)])
            before = epub_path.read_bytes()
            second = runner.invoke(cli, ["series", "backfill", "--all", "--db", str(db_path)])

        assert second.exit_code == 0, second.output
        assert epub_path.read_bytes() == before

    def test_dry_run_does_not_touch_epub(self, tmp_path: Path) -> None:
        epub_path = tmp_path / "eye.epub"
        _make_epub(epub_path, "The Eye of the World")
        db_path = tmp_path / "test.db"
        book_id = _add_book(
            db_path,
            "The Eye of the World",
            series="Already Set",
            series_index=2.0,
            output=epub_path,
        )

        with patch(
            "bookery.cli.commands.series_cmd._create_provider", return_value=FakeProvider()
        ):
            result = CliRunner().invoke(
                cli, ["series", "backfill", str(book_id), "--dry-run", "--db", str(db_path)]
            )

        assert result.exit_code == 0, result.output
        assert "1 EPUB" in result.output
        assert read_calibre_series(epub_path) == (None, None)

    def test_book_without_epub_is_skipped(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "The Eye of the World", series="Already Set")

        with patch(
            "bookery.cli.commands.series_cmd._create_provider", return_value=FakeProvider()
        ):
            result = CliRunner().invoke(
                cli, ["series", "backfill", str(book_id), "--db", str(db_path)]
            )

        assert result.exit_code == 0, result.output


class TestBackfillRespectsLocks:
    def test_locked_series_is_preserved(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "The Eye of the World", isbn="9780312850098")

        conn = open_library(db_path)
        LibraryCatalog(conn).set_field_lock(book_id, "series", True)
        conn.close()

        provider = FakeProvider({"9780312850098": _cand("The Wheel of Time", 1.0)})

        with patch("bookery.cli.commands.series_cmd._create_provider", return_value=provider):
            result = CliRunner().invoke(
                cli, ["series", "backfill", str(book_id), "--db", str(db_path)]
            )

        assert result.exit_code == 0
        assert _get_book(db_path, book_id).metadata.series is None

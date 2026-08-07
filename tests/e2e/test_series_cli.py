# ABOUTME: End-to-end tests for the `bookery series` CLI group.
# ABOUTME: Covers `series ls` coverage listing and `series backfill` provider/heuristic fills.

import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.mapping import BookRecord
from bookery.formats.epub import (
    EpubReadError,
    read_calibre_series,
    read_epub_metadata,
    write_epub_metadata,
)
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


def _make_unreadable_epub(path: Path) -> None:
    """Write a valid zip that is not a valid EPUB: no META-INF/container.xml.

    ``ZipFile.read`` raises ``KeyError`` for a missing member, which is how a
    truncated-then-repaired file or a mis-extensioned archive shows up.
    """
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")


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

    def test_second_run_rewrites_nothing(self, tmp_path: Path) -> None:
        """The staleness gate must stop the second run from touching the file at all.

        Byte equality can't prove this — ``write_epub_metadata`` is deterministic
        on repeat writes, so a rewritten file is byte-identical to a skipped one.
        The rewrite count is the only observable difference.
        """
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
            first = runner.invoke(cli, ["series", "backfill", "--all", "--db", str(db_path)])
            second = runner.invoke(cli, ["series", "backfill", "--all", "--db", str(db_path)])

        assert first.exit_code == 0, first.output
        assert "Updated series metadata in 1 EPUB file(s)." in first.output
        # The first run really pushed the series into the file.
        assert read_calibre_series(epub_path) == ("Already Set", 2.0)

        assert second.exit_code == 0, second.output
        assert "Updated series metadata in 0 EPUB file(s)." in second.output
        assert read_calibre_series(epub_path) == ("Already Set", 2.0)

    def test_high_precision_index_does_not_churn(self, tmp_path: Path) -> None:
        """An index beyond %g precision must not re-flag the EPUB every run."""
        epub_path = tmp_path / "eye.epub"
        _make_epub(epub_path, "The Eye of the World")
        db_path = tmp_path / "test.db"
        _add_book(
            db_path,
            "The Eye of the World",
            series="Already Set",
            series_index=1.123456789,
            output=epub_path,
        )
        runner = CliRunner()

        with patch(
            "bookery.cli.commands.series_cmd._create_provider", return_value=FakeProvider()
        ):
            first = runner.invoke(cli, ["series", "backfill", "--all", "--db", str(db_path)])
            second = runner.invoke(cli, ["series", "backfill", "--all", "--db", str(db_path)])

        assert first.exit_code == 0, first.output
        assert "failed" not in first.output
        # The write really happened, at %g precision
        assert "Updated series metadata in 1 EPUB file(s)." in first.output
        assert read_calibre_series(epub_path) == ("Already Set", 1.12346)
        # The catalog still holds full precision, so a naive float compare would
        # call the file stale forever and rewrite it on every run.
        assert second.exit_code == 0, second.output
        assert "Updated series metadata in 0 EPUB file(s)." in second.output


class TestBackfillEpubWriteFailures:
    """The atomic-write safety net: bad files are skipped, bad writes keep the original."""

    def test_unreadable_epub_is_reported_and_batch_continues(self, tmp_path: Path) -> None:
        """A zip missing container.xml raises KeyError; it must not abort the run."""
        broken_path = tmp_path / "broken.epub"
        _make_unreadable_epub(broken_path)
        good_path = tmp_path / "good.epub"
        _make_epub(good_path, "Good Book")
        db_path = tmp_path / "test.db"
        _add_book(db_path, "Broken Book", series="Broken Series", output=broken_path)
        _add_book(db_path, "Good Book", series="Good Series", output=good_path)

        with patch(
            "bookery.cli.commands.series_cmd._create_provider", return_value=FakeProvider()
        ):
            result = CliRunner().invoke(cli, ["series", "backfill", "--all", "--db", str(db_path)])

        assert result.exit_code == 0, result.output
        assert "Broken Book" in result.output
        assert "unreadable" in result.output
        # The healthy book was still written despite the other being skipped.
        assert read_calibre_series(good_path) == ("Good Series", None)
        assert "Updated series metadata in 1 EPUB file(s)." in result.output

    def test_verify_failure_keeps_original_and_reports(self, tmp_path: Path) -> None:
        """A write that drops the title must fail verify, even though series is right."""
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

        def lossy_write(path: Path, metadata: BookMetadata) -> None:
            # Series lands correctly; the title is clobbered. A series-only
            # verify would wave this through and swap in a damaged file.
            write_epub_metadata(path, replace(metadata, title="Clobbered Title"))

        with (
            patch("bookery.cli.commands.series_cmd._create_provider", return_value=FakeProvider()),
            patch("bookery.cli.commands.series_cmd.write_epub_metadata", lossy_write),
        ):
            result = CliRunner().invoke(cli, ["series", "backfill", "--all", "--db", str(db_path)])

        assert result.exit_code == 0, result.output
        assert "verify failed" in result.output
        assert "original kept" in result.output
        assert "1 failed" in result.output
        # The original is untouched: no series written, title intact.
        assert read_calibre_series(epub_path) == (None, None)
        assert read_epub_metadata(epub_path).title == "The Eye of the World"
        assert not list(tmp_path.glob("*.fixtmp"))

    def test_write_error_cleans_up_temp_and_keeps_original(self, tmp_path: Path) -> None:
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

        def exploding_write(path: Path, metadata: BookMetadata) -> None:
            raise EpubReadError("boom")

        with (
            patch("bookery.cli.commands.series_cmd._create_provider", return_value=FakeProvider()),
            patch("bookery.cli.commands.series_cmd.write_epub_metadata", exploding_write),
        ):
            result = CliRunner().invoke(cli, ["series", "backfill", "--all", "--db", str(db_path)])

        assert result.exit_code == 0, result.output
        assert "EPUB write failed" in result.output
        assert "1 failed" in result.output
        assert read_calibre_series(epub_path) == (None, None)
        # No orphaned temp file left behind in the library.
        assert not list(tmp_path.glob("*.fixtmp"))

    def test_hash_failure_after_swap_is_not_a_failed_write(self, tmp_path: Path) -> None:
        """The swap already succeeded, so a hashing error must not be counted as failed."""
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

        def unhashable(path: Path) -> str:
            raise OSError("hash device fell over")

        with (
            patch("bookery.cli.commands.series_cmd._create_provider", return_value=FakeProvider()),
            patch("bookery.cli.commands.series_cmd.compute_file_hash", unhashable),
        ):
            result = CliRunner().invoke(cli, ["series", "backfill", "--all", "--db", str(db_path)])

        assert result.exit_code == 0, result.output
        assert "Updated series metadata in 1 EPUB file(s)." in result.output
        assert "failed" not in result.output
        # The write landed even though the hash could not be recomputed.
        assert read_calibre_series(epub_path) == ("Already Set", 2.0)

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


class TestBackfillTitleCorrespondence:
    """A candidate about a different book donates nothing, to catalog or EPUB (#303)."""

    def test_unrelated_candidate_never_reaches_the_epub_file(self, tmp_path: Path) -> None:
        epub_path = tmp_path / "remnant.epub"
        local_title = "Book 17 - Force Heretic I - Remnant"
        _make_epub(epub_path, local_title)
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, local_title, output=epub_path)
        # High confidence, real series, completely different book.
        candidate = replace(
            _cand("Expeditionary Force", 17.0),
            metadata=BookMetadata(
                title="Expeditionary Force: Match Game",
                authors=["Craig Alanson"],
                series="Expeditionary Force",
                series_index=17.0,
            ),
        )
        provider = FakeProvider({local_title: candidate})

        with patch("bookery.cli.commands.series_cmd._create_provider", return_value=provider):
            result = CliRunner().invoke(
                cli, ["series", "backfill", str(book_id), "--db", str(db_path)]
            )

        assert result.exit_code == 0, result.output
        record = _get_book(db_path, book_id)
        assert record.metadata.series is None
        assert record.metadata.series_index is None
        assert read_calibre_series(epub_path) == (None, None)
        assert "does not correspond" in result.output

    def test_corresponding_candidate_still_writes_through_to_the_epub(
        self, tmp_path: Path
    ) -> None:
        epub_path = tmp_path / "eye.epub"
        _make_epub(epub_path, "The Eye of the World")
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "The Eye of the World", output=epub_path)
        provider = FakeProvider({"The Eye of the World": _cand("The Wheel of Time", 1.0)})

        with patch("bookery.cli.commands.series_cmd._create_provider", return_value=provider):
            result = CliRunner().invoke(
                cli, ["series", "backfill", str(book_id), "--db", str(db_path)]
            )

        assert result.exit_code == 0, result.output
        assert read_calibre_series(epub_path) == ("The Wheel of Time", 1.0)


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

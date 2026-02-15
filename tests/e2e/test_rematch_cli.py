# ABOUTME: End-to-end tests for the bookery rematch CLI command.
# ABOUTME: Tests the full rematch pipeline using CliRunner with fake providers.

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.hashing import compute_file_hash
from bookery.formats.epub import read_epub_metadata
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata


def _make_candidate(
    title: str, author: str, confidence: float, isbn: str | None = None,
) -> MetadataCandidate:
    return MetadataCandidate(
        metadata=BookMetadata(title=title, authors=[author], isbn=isbn, language="en"),
        confidence=confidence,
        source="openlibrary",
        source_id=f"test-{title}",
    )


def _import_book(
    epub_path: Path, db_path: Path,
) -> int:
    """Import a single book into the catalog and return its ID."""
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    metadata = read_epub_metadata(epub_path)
    metadata.source_path = epub_path
    file_hash = compute_file_hash(epub_path)
    book_id = catalog.add_book(metadata, file_hash=file_hash)
    conn.close()
    return book_id


class TestRematchValidation:
    """E2E tests for rematch argument validation."""

    def test_rematch_no_arguments(self, tmp_path: Path) -> None:
        """No id, no --all, no --tag shows error."""
        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(cli, ["rematch", "--db", str(db_path)])

        assert result.exit_code != 0
        assert "Specify exactly one" in result.output

    def test_rematch_nonexistent_id(self, sample_epub: Path, tmp_path: Path) -> None:
        """Nonexistent book ID shows error."""
        db_path = tmp_path / "test.db"
        _import_book(sample_epub, db_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["rematch", "999", "--db", str(db_path)])

        assert result.exit_code == 0
        assert "not found" in result.output.lower()

    def test_rematch_nonexistent_tag(self, sample_epub: Path, tmp_path: Path) -> None:
        """Nonexistent tag shows error."""
        db_path = tmp_path / "test.db"
        _import_book(sample_epub, db_path)

        runner = CliRunner()
        result = runner.invoke(
            cli, ["rematch", "--tag", "nonexistent", "--db", str(db_path)],
        )

        assert result.exit_code == 0
        assert "not found" in result.output.lower()

    def test_rematch_empty_catalog_all(self, tmp_path: Path) -> None:
        """--all on empty catalog shows 'no books' message."""
        db_path = tmp_path / "test.db"
        # Create empty DB
        conn = open_library(db_path)
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["rematch", "--all", "--db", str(db_path)])

        assert result.exit_code == 0
        assert "no books" in result.output.lower()


class TestRematchQuietMode:
    """E2E tests for rematch in quiet mode (auto-accept)."""

    def test_rematch_single_book_quiet(self, sample_epub: Path, tmp_path: Path) -> None:
        """Full pipeline: import -> rematch -> verify DB updated."""
        db_path = tmp_path / "test.db"
        output_dir = tmp_path / "output"
        book_id = _import_book(sample_epub, db_path)

        candidate = _make_candidate("Il Nome della Rosa", "Umberto Eco", 0.95)

        with patch(
            "bookery.cli.commands.rematch_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "rematch", str(book_id),
                    "-q", "--db", str(db_path),
                    "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "1 matched" in result.output

        # Verify DB was updated
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        record = catalog.get_by_id(book_id)
        assert record.metadata.title == "Il Nome della Rosa"
        assert record.output_path is not None
        conn.close()

    def test_rematch_all_quiet(
        self, sample_epub: Path, minimal_epub: Path, tmp_path: Path,
    ) -> None:
        """Multiple books, all processed with --all -q."""
        db_path = tmp_path / "test.db"
        output_dir = tmp_path / "output"

        # Import two books
        scan_dir = tmp_path / "books"
        scan_dir.mkdir()
        epub1 = scan_dir / "book1.epub"
        epub2 = scan_dir / "book2.epub"
        shutil.copy(sample_epub, epub1)
        shutil.copy(minimal_epub, epub2)

        _import_book(epub1, db_path)
        _import_book(epub2, db_path)

        candidate = _make_candidate("Matched Book", "Author", 0.95)

        with patch(
            "bookery.cli.commands.rematch_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "rematch", "--all",
                    "-q", "--db", str(db_path),
                    "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "2 matched" in result.output

    def test_rematch_tag_quiet(self, sample_epub: Path, tmp_path: Path) -> None:
        """Only tagged books are processed."""
        db_path = tmp_path / "test.db"
        output_dir = tmp_path / "output"

        book_id = _import_book(sample_epub, db_path)

        # Tag the book
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.add_tag(book_id, "fiction")
        conn.close()

        candidate = _make_candidate("Tagged Match", "Author", 0.95)

        with patch(
            "bookery.cli.commands.rematch_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "rematch", "--tag", "fiction",
                    "-q", "--db", str(db_path),
                    "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "1 matched" in result.output


class TestRematchInteractive:
    """E2E tests for interactive rematch."""

    def test_rematch_interactive_accept(self, sample_epub: Path, tmp_path: Path) -> None:
        """input='1\\n' selects the first candidate."""
        db_path = tmp_path / "test.db"
        output_dir = tmp_path / "output"
        book_id = _import_book(sample_epub, db_path)

        candidate = _make_candidate("Interactive Match", "Author", 0.85)

        with patch(
            "bookery.cli.commands.rematch_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "rematch", str(book_id),
                    "--db", str(db_path),
                    "-o", str(output_dir),
                ],
                input="1\n",
            )

        assert result.exit_code == 0, result.output
        assert "1 matched" in result.output

    def test_rematch_interactive_skip(self, sample_epub: Path, tmp_path: Path) -> None:
        """input='s\\n' skips the book."""
        db_path = tmp_path / "test.db"
        output_dir = tmp_path / "output"
        book_id = _import_book(sample_epub, db_path)

        candidate = _make_candidate("Skip Me", "Author", 0.85)

        with patch(
            "bookery.cli.commands.rematch_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "rematch", str(book_id),
                    "--db", str(db_path),
                    "-o", str(output_dir),
                ],
                input="s\n",
            )

        assert result.exit_code == 0, result.output
        assert "1 skipped" in result.output

        # Verify DB was NOT updated
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        record = catalog.get_by_id(book_id)
        assert record.output_path is None
        conn.close()


class TestRematchResume:
    """E2E tests for --resume / --no-resume behavior."""

    def test_resume_skips_books_with_output_path(
        self, sample_epub: Path, tmp_path: Path,
    ) -> None:
        """Books with output_path set are skipped in resume mode."""
        db_path = tmp_path / "test.db"
        output_dir = tmp_path / "output"

        book_id = _import_book(sample_epub, db_path)

        # Simulate a previous match by setting output_path
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.set_output_path(book_id, tmp_path / "already_matched.epub")
        conn.close()

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "rematch", str(book_id),
                "-q", "--db", str(db_path),
                "-o", str(output_dir),
            ],
        )

        assert result.exit_code == 0
        assert "already matched" in result.output.lower()

    def test_no_resume_reprocesses_all(
        self, sample_epub: Path, tmp_path: Path,
    ) -> None:
        """--no-resume processes books even if output_path is set."""
        db_path = tmp_path / "test.db"
        output_dir = tmp_path / "output"

        book_id = _import_book(sample_epub, db_path)

        # Simulate a previous match
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.set_output_path(book_id, tmp_path / "already_matched.epub")
        conn.close()

        candidate = _make_candidate("Rematched", "Author", 0.95)

        with patch(
            "bookery.cli.commands.rematch_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "rematch", str(book_id),
                    "-q", "--no-resume",
                    "--db", str(db_path),
                    "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "1 matched" in result.output


class TestRematchSummary:
    """E2E tests for summary counts."""

    def test_rematch_summary_counts(
        self, sample_epub: Path, minimal_epub: Path, tmp_path: Path,
    ) -> None:
        """Summary shows matched/skipped/error counts."""
        db_path = tmp_path / "test.db"
        output_dir = tmp_path / "output"

        # Import two books
        scan_dir = tmp_path / "books"
        scan_dir.mkdir()
        epub1 = scan_dir / "book1.epub"
        epub2 = scan_dir / "book2.epub"
        shutil.copy(sample_epub, epub1)
        shutil.copy(minimal_epub, epub2)

        _import_book(epub1, db_path)
        _import_book(epub2, db_path)

        # First book matches, second gets no candidates
        candidate = _make_candidate("Matched Only", "Author", 0.95)

        call_count = 0

        def search_side_effect(title, author=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [candidate]
            return []

        with patch(
            "bookery.cli.commands.rematch_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.side_effect = search_side_effect
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "rematch", "--all",
                    "-q", "--db", str(db_path),
                    "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "1 matched" in result.output
        assert "1 skipped" in result.output

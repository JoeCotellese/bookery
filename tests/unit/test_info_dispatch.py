# ABOUTME: Unit tests for the `bookery info` command's ID-vs-path dispatch.
# ABOUTME: Covers numeric IDs, file paths, ambiguity, and the deprecated `inspect` alias.

from pathlib import Path

import pytest
from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli
from bookery.cli.deprecation import reset_deprecation_state
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


def _make_epub(path: Path, title: str, author: str = "Some Author") -> Path:
    book = epub.EpubBook()
    book.set_identifier(f"id-{title}")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)

    chapter = epub.EpubHtml(
        title="Chapter 1", file_name="chap01.xhtml", lang="en",
    )
    chapter.content = b"<html><body><h1>Chapter 1</h1><p>x.</p></body></html>"
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)
    return path


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    db_path = tmp_path / "lib.db"
    conn = open_library(db_path)
    LibraryCatalog(conn).add_book(
        BookMetadata(
            title="Dune",
            authors=["Frank Herbert"],
            source_path=Path("/tmp/dune.epub"),
        ),
        file_hash="h" * 64,
    )
    conn.close()
    return db_path


class TestInfoIdDispatch:
    """`info <id>` continues to work the same as before."""

    def test_info_with_numeric_id_shows_book_record(self, db_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["info", "1", "--db", str(db_path)])
        assert result.exit_code == 0, result.output
        assert "Dune" in result.output
        assert "Frank Herbert" in result.output

    def test_info_with_missing_id_errors_with_helpful_message(
        self, db_path: Path,
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["info", "999", "--db", str(db_path)])
        assert result.exit_code != 0
        # Tells the user both lookup attempts so they understand what failed.
        assert "999" in result.output


class TestInfoPathDispatch:
    """`info <path>` reads a loose EPUB file on disk (was inspect's job)."""

    def test_info_with_path_shows_extracted_metadata(
        self, tmp_path: Path,
    ) -> None:
        source = _make_epub(tmp_path / "book.epub", "Foundation", "Isaac Asimov")
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(source)])
        assert result.exit_code == 0, result.output
        assert "Foundation" in result.output
        assert "Isaac Asimov" in result.output

    def test_info_with_extensioned_path_dispatches_as_path(
        self, tmp_path: Path,
    ) -> None:
        """An arg ending in .epub is always treated as a path, never an ID."""
        source = _make_epub(tmp_path / "rose.epub", "Rose", "Eco")
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(source)])
        assert result.exit_code == 0, result.output
        assert "Rose" in result.output

    def test_info_with_nonexistent_path_errors(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["info", "/nonexistent/path.epub"])
        assert result.exit_code != 0


class TestInfoAmbiguousArg:
    """Ambiguous args (e.g. bare numeric string) try ID first, then fall back."""

    def test_info_numeric_arg_prefers_id_lookup(self, db_path: Path) -> None:
        """A bare integer always tries the catalog first."""
        runner = CliRunner()
        result = runner.invoke(cli, ["info", "1", "--db", str(db_path)])
        assert result.exit_code == 0, result.output
        assert "Dune" in result.output

    def test_info_unknown_bare_arg_reports_both_lookups(
        self, db_path: Path,
    ) -> None:
        """When neither ID nor path resolves, the error mentions both."""
        runner = CliRunner()
        result = runner.invoke(cli, ["info", "bogus", "--db", str(db_path)])
        assert result.exit_code != 0
        # Error mentions both lookup attempts so the user can diagnose.
        assert "bogus" in result.output


class TestInspectDeprecatedAlias:
    """`inspect <path>` still works but warns and forwards to `info`."""

    def test_inspect_path_still_works(self, tmp_path: Path) -> None:
        reset_deprecation_state()
        source = _make_epub(tmp_path / "book.epub", "Foundation", "Isaac Asimov")
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", str(source)])
        assert result.exit_code == 0, result.output
        assert "Foundation" in result.output
        # Deprecation warning to stderr
        assert "'inspect' is deprecated" in result.stderr
        assert "'info'" in result.stderr

    def test_inspect_nonexistent_path_errors(self) -> None:
        reset_deprecation_state()
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", "/nonexistent/path.epub"])
        assert result.exit_code != 0

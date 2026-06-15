# ABOUTME: E2E tests for the `bookery authors fix-sort` file-as backfill command.
# ABOUTME: Seeds a real catalog + EPUBs lacking file-as and drives the CLI.

from pathlib import Path

from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.formats.epub import read_creator_file_as
from bookery.metadata import BookMetadata


def _make_epub(path: Path, title: str, authors: list[str]) -> None:
    """Write a minimal EPUB whose creators carry no file-as (reproduces the bug)."""
    book = epub.EpubBook()
    book.set_identifier(f"id-{title}")
    book.set_title(title)
    book.set_language("en")
    for author in authors:
        book.add_author(author)  # no file_as -> the broken state we backfill
    chapter = epub.EpubHtml(title="c", file_name="c.xhtml", lang="en")
    chapter.content = b"<html><body><p>x</p></body></html>"
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)


def _seed(db_path: Path, title: str, authors: list[str], output: Path) -> int:
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    book_id = catalog.add_book(
        BookMetadata(title=title, authors=authors, source_path=output),
        file_hash=f"hash-{title}",
        output_path=output,
    )
    conn.close()
    return book_id


class TestAuthorsFixSort:
    def test_dry_run_lists_candidate_and_writes_nothing(self, tmp_path: Path) -> None:
        epub_path = tmp_path / "way_of_kings.epub"
        _make_epub(epub_path, "The Way of Kings", ["Sanderson, Brandon"])
        db_path = tmp_path / "lib.db"
        _seed(db_path, "The Way of Kings", ["Sanderson, Brandon"], epub_path)

        result = CliRunner().invoke(cli, ["--db", str(db_path), "authors", "fix-sort"])

        assert result.exit_code == 0, result.output
        assert "The Way of Kings" in result.output
        # Dry run must not touch the file.
        assert read_creator_file_as(epub_path) == [("Sanderson, Brandon", None)]

    def test_apply_writes_file_as_and_updates_hash(self, tmp_path: Path) -> None:
        epub_path = tmp_path / "way_of_kings.epub"
        _make_epub(epub_path, "The Way of Kings", ["Sanderson, Brandon"])
        db_path = tmp_path / "lib.db"
        book_id = _seed(
            db_path, "The Way of Kings", ["Sanderson, Brandon"], epub_path
        )

        result = CliRunner().invoke(
            cli, ["--db", str(db_path), "authors", "fix-sort", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert read_creator_file_as(epub_path) == [
            ("Sanderson, Brandon", "Sanderson, Brandon")
        ]
        conn = open_library(db_path)
        record = LibraryCatalog(conn).get_by_id(book_id)
        conn.close()
        assert record is not None
        assert record.file_hash != "hash-The Way of Kings"

    def test_apply_is_idempotent(self, tmp_path: Path) -> None:
        epub_path = tmp_path / "always.epub"
        _make_epub(epub_path, "Always Be Testing", ["Eisenberg, Bryan"])
        db_path = tmp_path / "lib.db"
        _seed(db_path, "Always Be Testing", ["Eisenberg, Bryan"], epub_path)
        runner = CliRunner()

        runner.invoke(cli, ["--db", str(db_path), "authors", "fix-sort", "--apply"])
        second = runner.invoke(
            cli, ["--db", str(db_path), "authors", "fix-sort", "--apply"]
        )

        assert second.exit_code == 0, second.output
        # Nothing left to fix on the second pass.
        assert "Always Be Testing" not in second.output
        assert read_creator_file_as(epub_path) == [
            ("Eisenberg, Bryan", "Eisenberg, Bryan")
        ]

    def test_coauthors_left_intact(self, tmp_path: Path) -> None:
        epub_path = tmp_path / "barbarians.epub"
        _make_epub(epub_path, "Barbarians", ["Bryan Burrough", "John Helyar"])
        db_path = tmp_path / "lib.db"
        _seed(db_path, "Barbarians", ["Bryan Burrough", "John Helyar"], epub_path)

        CliRunner().invoke(
            cli, ["--db", str(db_path), "authors", "fix-sort", "--apply"]
        )

        assert read_creator_file_as(epub_path) == [
            ("Bryan Burrough", "Burrough, Bryan"),
            ("John Helyar", "Helyar, John"),
        ]

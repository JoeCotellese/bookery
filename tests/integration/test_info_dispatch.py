# ABOUTME: Integration tests for the `bookery info` command's ID/path dispatch.
# ABOUTME: Verifies the dispatch interacts correctly with the catalog and EPUB readers.

from pathlib import Path

import pytest
from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli
from bookery.cli.deprecation import reset_deprecation_state
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


def _make_epub(path: Path, title: str, author: str = "A") -> Path:
    book = epub.EpubBook()
    book.set_identifier(f"id-{title}")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)
    chapter = epub.EpubHtml(title="C1", file_name="c.xhtml", lang="en")
    chapter.content = b"<html><body><p>x</p></body></html>"
    book.add_item(chapter)
    book.toc = [epub.Link("c.xhtml", "C1", "c")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)
    return path


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "lib.db"
    conn = open_library(p)
    LibraryCatalog(conn).add_book(
        BookMetadata(
            title="Cataloged Book",
            authors=["Cat Author"],
            source_path=Path("/tmp/cat.epub"),
        ),
        file_hash="c" * 64,
    )
    conn.close()
    return p


class TestInfoCatalogAndPathTogether:
    """Catalog read and disk read share the `info` surface."""

    def test_info_id_uses_catalog_data_not_disk(self, db_path: Path, tmp_path: Path) -> None:
        """`info <id>` reads from the catalog, not from a file on disk."""
        runner = CliRunner()
        # No file on disk for the cataloged book — catalog read still works.
        result = runner.invoke(cli, ["info", "1", "--db", str(db_path)])
        assert result.exit_code == 0, result.output
        assert "Cataloged Book" in result.output

    def test_info_path_reads_disk_metadata_directly(
        self,
        db_path: Path,
        tmp_path: Path,
    ) -> None:
        """`info <path>` reads from disk even when a catalog is configured."""
        loose = _make_epub(tmp_path / "loose.epub", "Loose Title", "Loose Author")
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(loose), "--db", str(db_path)])
        assert result.exit_code == 0, result.output
        assert "Loose Title" in result.output
        # Catalog row is NOT shown — this is the disk-read path.
        assert "Cataloged Book" not in result.output

    def test_info_path_with_catalog_flags_rejected(
        self,
        db_path: Path,
        tmp_path: Path,
    ) -> None:
        """`info <path> --set ...` is operator error — flags need a catalog ID."""
        loose = _make_epub(tmp_path / "loose.epub", "Loose", "Author")
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["info", str(loose), "--db", str(db_path), "--set", "title=Nope"],
        )
        assert result.exit_code != 0
        assert "cataloged" in result.output.lower()


class TestInspectAliasForwarding:
    """The `inspect` deprecated alias forwards every arg shape to `info`."""

    def test_inspect_with_path_works(self, tmp_path: Path) -> None:
        reset_deprecation_state()
        loose = _make_epub(tmp_path / "loose.epub", "Through The Alias", "X")
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", str(loose)])
        assert result.exit_code == 0, result.output
        assert "Through The Alias" in result.output
        assert "'inspect' is deprecated" in result.stderr

    def test_inspect_with_cataloged_id_also_forwards(self, db_path: Path) -> None:
        """`inspect <id>` is unusual but the alias forwards any argument."""
        reset_deprecation_state()
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", "1", "--db", str(db_path)])
        assert result.exit_code == 0, result.output
        assert "Cataloged Book" in result.output
        assert "'inspect' is deprecated" in result.stderr

# ABOUTME: Integration tests for the `bookery add` command end-to-end.
# ABOUTME: Exercises full copy → catalog flow with real DB and file operations.

from pathlib import Path

from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library


def _make_epub(path: Path, title: str, author: str = "Integration Author") -> Path:
    book = epub.EpubBook()
    book.set_identifier(f"id-{title}")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)

    chapter = epub.EpubHtml(
        title="Chapter 1", file_name="chap01.xhtml", lang="en",
    )
    chapter.content = (
        b"<html><body><h1>Chapter 1</h1><p>" + title.encode() + b".</p></body></html>"
    )
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)
    return path


class TestAddIntegration:
    def test_add_full_flow_copies_and_catalogs(
        self, tmp_path: Path, _isolate_library_root: Path,
    ) -> None:
        library_root = _isolate_library_root
        db_path = tmp_path / "catalog.db"
        source = _make_epub(tmp_path / "source.epub", "Perdido Street Station", "China Mieville")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["add", str(source), "--db", str(db_path), "--no-match"],
        )

        assert result.exit_code == 0, result.output
        # Source preserved
        assert source.exists()
        # Library contains a copy somewhere under library_root
        copies = list(library_root.rglob("*.epub"))
        assert len(copies) == 1
        assert copies[0] != source

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        records = catalog.list_all()
        assert len(records) == 1
        assert records[0].metadata.title == "Perdido Street Station"
        conn.close()

    def test_add_move_with_real_epub(
        self, tmp_path: Path, _isolate_library_root: Path,
    ) -> None:
        library_root = _isolate_library_root
        db_path = tmp_path / "catalog.db"
        source = _make_epub(tmp_path / "source.epub", "The Scar", "China Mieville")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["add", str(source), "--db", str(db_path), "--no-match", "--move"],
        )

        assert result.exit_code == 0, result.output
        assert not source.exists(), "source should be deleted with --move"
        copies = list(library_root.rglob("*.epub"))
        assert len(copies) == 1

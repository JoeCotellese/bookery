# ABOUTME: Unit tests for the `bookery add` command (single-file + directory dispatch).
# ABOUTME: Covers copy-by-default, --move, --no-match, idempotency, and `import` alias.

from pathlib import Path

import pytest
from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli
from bookery.cli.deprecation import reset_deprecation_state
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library


def _make_epub(
    path: Path,
    title: str,
    author: str = "Some Author",
    *,
    content_marker: str = "",
) -> Path:
    book = epub.EpubBook()
    book.set_identifier(f"id-{title}-{content_marker}")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)

    chapter = epub.EpubHtml(
        title="Chapter 1", file_name="chap01.xhtml", lang="en",
    )
    chapter.content = (
        b"<html><body><h1>Chapter 1</h1><p>"
        + title.encode()
        + b" "
        + content_marker.encode()
        + b".</p></body></html>"
    )
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)
    return path


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "catalog.db"


@pytest.fixture()
def library_root(_isolate_library_root: Path) -> Path:
    return _isolate_library_root


class TestAddCommand:
    def test_add_single_file_copies_to_library(
        self, tmp_path: Path, db_path: Path, library_root: Path,
    ) -> None:
        source = _make_epub(tmp_path / "book.epub", "Foundation", "Isaac Asimov")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["add", str(source), "--db", str(db_path), "--no-match"],
        )

        assert result.exit_code == 0, result.output
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        records = catalog.list_all()
        assert len(records) == 1
        output_path = records[0].output_path
        assert output_path is not None
        assert Path(output_path).is_absolute() or (library_root / output_path).exists()
        conn.close()

    def test_add_source_preserved_by_default(
        self, tmp_path: Path, db_path: Path,
    ) -> None:
        source = _make_epub(tmp_path / "book.epub", "Dune", "Frank Herbert")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["add", str(source), "--db", str(db_path), "--no-match"],
        )

        assert result.exit_code == 0, result.output
        assert source.exists(), "source should not be deleted by default"

    def test_add_move_deletes_source(
        self, tmp_path: Path, db_path: Path,
    ) -> None:
        source = _make_epub(tmp_path / "book.epub", "Neuromancer", "William Gibson")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["add", str(source), "--db", str(db_path), "--no-match", "--move"],
        )

        assert result.exit_code == 0, result.output
        assert not source.exists(), "source should be deleted with --move"

    def test_add_move_preserves_source_when_idempotent(
        self, db_path: Path, library_root: Path,
    ) -> None:
        library_root.mkdir(parents=True, exist_ok=True)
        source = _make_epub(library_root / "book.epub", "Hyperion", "Dan Simmons")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["add", str(source), "--db", str(db_path), "--no-match", "--move"],
        )

        assert result.exit_code == 0, result.output
        assert source.exists(), "source inside library_root must never be unlinked"

    def test_add_rejects_non_epub(
        self, tmp_path: Path, db_path: Path,
    ) -> None:
        bad = tmp_path / "notabook.txt"
        bad.write_text("hello")

        runner = CliRunner()
        result = runner.invoke(cli, ["add", str(bad), "--db", str(db_path)])

        assert result.exit_code != 0
        assert "epub" in result.output.lower() or "not" in result.output.lower()

    def test_add_duplicate_hash_reports_existing(
        self, tmp_path: Path, db_path: Path,
    ) -> None:
        source = _make_epub(tmp_path / "book.epub", "1984", "George Orwell")

        runner = CliRunner()
        r1 = runner.invoke(
            cli, ["add", str(source), "--db", str(db_path), "--no-match"],
        )
        assert r1.exit_code == 0, r1.output

        # Re-add same file
        r2 = runner.invoke(
            cli, ["add", str(source), "--db", str(db_path), "--no-match"],
        )
        assert r2.exit_code == 0, r2.output

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        assert len(catalog.list_all()) == 1
        conn.close()

    def test_add_idempotent_inside_library(
        self, db_path: Path, library_root: Path,
    ) -> None:
        library_root.mkdir(parents=True, exist_ok=True)
        author_dir = library_root / "Gibson, William"
        author_dir.mkdir()
        source = _make_epub(author_dir / "inside.epub", "Count Zero", "William Gibson")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["add", str(source), "--db", str(db_path), "--no-match"],
        )

        assert result.exit_code == 0, result.output
        assert source.exists()
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        records = catalog.list_all()
        assert len(records) == 1
        # Output path should point at the existing location (no copy made)
        op = records[0].output_path
        assert op is not None
        assert Path(op) == source or (library_root / op) == source
        conn.close()

    def test_add_no_match_skips_pipeline(
        self, tmp_path: Path, db_path: Path,
    ) -> None:
        source = _make_epub(tmp_path / "book.epub", "Solaris", "Stanislaw Lem")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["add", str(source), "--db", str(db_path), "--no-match"],
        )

        assert result.exit_code == 0, result.output
        # No network / match activity should be required; record has extracted title
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        records = catalog.list_all()
        assert len(records) == 1
        assert records[0].metadata.title == "Solaris"
        conn.close()

    def test_add_quiet_with_no_match_warns(
        self, tmp_path: Path, db_path: Path,
    ) -> None:
        source = _make_epub(tmp_path / "book.epub", "Roadside Picnic", "Strugatsky")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "add", str(source),
                "--db", str(db_path),
                "--no-match", "--quiet",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "warn" in result.output.lower() or "ignor" in result.output.lower()


class TestAddDispatch:
    """Dispatch behavior: `add` accepts both files and directories."""

    def test_add_directory_scans_and_catalogs(
        self, tmp_path: Path, db_path: Path,
    ) -> None:
        """`add <dir>` walks the directory and catalogs each EPUB found."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        _make_epub(scan_dir / "a.epub", "Alpha", "Author A")
        _make_epub(scan_dir / "b.epub", "Beta", "Author B")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["add", str(scan_dir), "--db", str(db_path)],
        )

        assert result.exit_code == 0, result.output
        assert "2" in result.output  # two EPUBs reported
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        assert len(catalog.list_all()) == 2
        conn.close()

    def test_add_empty_directory_reports_nothing_found(
        self, tmp_path: Path, db_path: Path,
    ) -> None:
        """`add <empty-dir>` reports no EPUB files and exits 0."""
        empty = tmp_path / "empty"
        empty.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            cli, ["add", str(empty), "--db", str(db_path)],
        )

        assert result.exit_code == 0, result.output
        assert "No EPUB files found" in result.output

    def test_add_missing_path_errors(
        self, tmp_path: Path, db_path: Path,
    ) -> None:
        """`add <missing>` errors out with a clear message."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["add", str(tmp_path / "nope.epub"), "--db", str(db_path)],
        )

        assert result.exit_code != 0
        # Click's standard "does not exist" message
        assert "not exist" in result.output.lower() or "no such" in result.output.lower()

    def test_add_directory_force_duplicates_flag_available(
        self, tmp_path: Path, db_path: Path,
    ) -> None:
        """`add <dir>` accepts --force-duplicates (preserved from import)."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        # Distinct bytes (different content_marker → different hash) but same
        # title+author so metadata-level dedup would normally skip the second.
        _make_epub(
            scan_dir / "rose_v1.epub", "Dup Title", "Dup Author",
            content_marker="v1",
        )
        _make_epub(
            scan_dir / "rose_v2.epub", "Dup Title", "Dup Author",
            content_marker="v2",
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "add", str(scan_dir),
                "--db", str(db_path),
                "--force-duplicates",
            ],
        )

        assert result.exit_code == 0, result.output
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        assert len(catalog.list_all()) == 2
        conn.close()

    def test_add_directory_output_dir_flag_available(
        self, tmp_path: Path, db_path: Path,
    ) -> None:
        """`add <dir> -o <dir>` accepts --output-dir (preserved from import)."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        _make_epub(scan_dir / "a.epub", "Alpha", "Author A")
        output_dir = tmp_path / "lib"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "add", str(scan_dir),
                "--db", str(db_path),
                "-o", str(output_dir),
            ],
        )

        assert result.exit_code == 0, result.output
        assert any(output_dir.rglob("*.epub")), "EPUB should be copied to output-dir"


class TestImportDeprecatedAlias:
    """`import` is a deprecated alias that forwards to `add`."""

    def test_import_file_still_works(
        self, tmp_path: Path, db_path: Path,
    ) -> None:
        """`import <file>` works and prints a deprecation warning."""
        reset_deprecation_state()
        source = _make_epub(tmp_path / "book.epub", "Foundation", "Isaac Asimov")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["import", str(source), "--db", str(db_path), "--no-match"],
        )

        assert result.exit_code == 0, result.output
        # Deprecation warning routes to stderr (separated by default in Click 8.4)
        assert "'import' is deprecated" in result.stderr
        assert "'add'" in result.stderr

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        assert len(catalog.list_all()) == 1
        conn.close()

    def test_import_directory_still_works(
        self, tmp_path: Path, db_path: Path,
    ) -> None:
        """`import <dir>` works and prints a deprecation warning."""
        reset_deprecation_state()
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        _make_epub(scan_dir / "a.epub", "Alpha", "Author A")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["import", str(scan_dir), "--db", str(db_path)],
        )

        assert result.exit_code == 0, result.output
        assert "'import' is deprecated" in result.stderr
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        assert len(catalog.list_all()) == 1
        conn.close()

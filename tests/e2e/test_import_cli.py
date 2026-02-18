# ABOUTME: End-to-end tests for the `bookery import` CLI command with DB integration.
# ABOUTME: Validates command output, DB creation, --db flag, --convert flag, and dedup reporting.

import shutil
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli
from bookery.core.converter import ConvertResult
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library


def _make_epub_unique(
    path: Path, title: str, author: str, *, content_marker: str = "",
) -> Path:
    """Create a minimal EPUB with unique content to produce distinct hashes."""
    book = epub.EpubBook()
    book.set_identifier(f"id-{title}-{content_marker}")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)

    chapter = epub.EpubHtml(
        title="Chapter 1", file_name="chap01.xhtml", lang="en",
    )
    chapter.content = (
        b"<html><body><h1>Chapter 1</h1>"
        b"<p>Content: " + content_marker.encode() + b".</p>"
        b"</body></html>"
    )
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(path), book)
    return path


class TestImportCommand:
    """E2E tests for the bookery import command."""

    def test_import_creates_db(
        self, sample_epub: Path, tmp_path: Path,
    ) -> None:
        """Import creates a database file and catalogs the EPUB."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "rose.epub")

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["import", str(scan_dir), "--db", str(db_path)],
        )

        assert result.exit_code == 0
        assert db_path.exists()

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        records = catalog.list_all()
        assert len(records) == 1
        assert records[0].metadata.title == "The Name of the Rose"
        conn.close()

    def test_import_shows_summary(
        self, sample_epub: Path, minimal_epub: Path, tmp_path: Path,
    ) -> None:
        """Import output shows added count."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "rose.epub")
        shutil.copy(minimal_epub, scan_dir / "minimal.epub")

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["import", str(scan_dir), "--db", str(db_path)],
        )

        assert result.exit_code == 0
        assert "2" in result.output  # 2 files processed
        assert "added" in result.output.lower()

    def test_import_reimport_shows_skipped(
        self, sample_epub: Path, tmp_path: Path,
    ) -> None:
        """Second import of same files shows skipped count."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "rose.epub")

        db_path = tmp_path / "test.db"
        runner = CliRunner()

        runner.invoke(cli, ["import", str(scan_dir), "--db", str(db_path)])
        result = runner.invoke(
            cli, ["import", str(scan_dir), "--db", str(db_path)],
        )

        assert result.exit_code == 0
        assert "skipped" in result.output.lower()

    def test_import_empty_directory(self, tmp_path: Path) -> None:
        """Import command reports when no EPUBs are found."""
        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["import", str(tmp_path), "--db", str(db_path)],
        )

        assert result.exit_code == 0
        assert "No EPUB files found" in result.output

    def test_import_handles_corrupt_files(
        self, sample_epub: Path, corrupt_epub: Path, tmp_path: Path,
    ) -> None:
        """Import handles corrupt files without crashing."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "rose.epub")
        shutil.copy(corrupt_epub, scan_dir / "bad.epub")

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["import", str(scan_dir), "--db", str(db_path)],
        )

        assert result.exit_code == 0
        assert "error" in result.output.lower()

        # Good file should still be imported
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        records = catalog.list_all()
        assert len(records) == 1
        conn.close()

    def test_import_with_convert_catalogs_mobis(
        self, sample_epub: Path, tmp_path: Path,
    ) -> None:
        """MOBI file + --convert → converted EPUB is cataloged in DB."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        mobi_file = scan_dir / "rose.mobi"
        mobi_file.write_bytes(b"fake mobi content")

        # The mock convert_one will return a ConvertResult pointing to the
        # real sample_epub fixture so the import pipeline can read metadata.
        fake_result = ConvertResult(
            source=mobi_file,
            epub_path=sample_epub,
            success=True,
        )

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        with patch(
            "bookery.core.converter.convert_one",
            return_value=fake_result,
        ):
            result = runner.invoke(
                cli,
                ["import", str(scan_dir), "--convert", "--db", str(db_path)],
            )

        assert result.exit_code == 0, result.output
        assert "rose.mobi" in result.output  # per-file progress
        assert "done" in result.output  # per-file status
        assert "Converted 1 of 1" in result.output  # summary

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        records = catalog.list_all()
        assert len(records) == 1
        assert records[0].metadata.title == "The Name of the Rose"
        conn.close()

    def test_import_without_convert_ignores_mobis(
        self, tmp_path: Path,
    ) -> None:
        """MOBI-only directory without --convert → 'No EPUB files found'."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        (scan_dir / "book.mobi").write_bytes(b"fake mobi")

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["import", str(scan_dir), "--db", str(db_path)],
        )

        assert result.exit_code == 0
        assert "No EPUB files found" in result.output

    def test_import_convert_rerun_skips_already_converted(
        self, sample_epub: Path, tmp_path: Path,
    ) -> None:
        """Re-running --convert shows 'skipped' for already-processed MOBIs."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        mobi_file = scan_dir / "rose.mobi"
        mobi_file.write_bytes(b"fake mobi content")

        # Simulate manifest-hit: skipped=True, epub_path=None
        skipped_result = ConvertResult(
            source=mobi_file,
            epub_path=None,
            success=True,
            skipped=True,
        )

        # Put the converted EPUB where rglob can find it
        output_dir = tmp_path / "bookery-output"
        epub_subdir = output_dir / "Author" / "Title"
        epub_subdir.mkdir(parents=True)
        shutil.copy(sample_epub, epub_subdir / "rose.epub")

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        with patch(
            "bookery.core.converter.convert_one",
            return_value=skipped_result,
        ):
            result = runner.invoke(
                cli,
                [
                    "import", str(scan_dir), "--convert",
                    "--db", str(db_path),
                    "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "skipped" in result.output
        assert "rose.mobi" in result.output

    def test_import_convert_skips_mobi_when_epub_exists(
        self, sample_epub: Path, tmp_path: Path,
    ) -> None:
        """MOBI + EPUB in same dir + --convert → MOBI not converted, skip reported."""
        scan_dir = tmp_path / "scan"
        book_dir = scan_dir / "Author" / "Title"
        book_dir.mkdir(parents=True)
        shutil.copy(sample_epub, book_dir / "book.epub")
        (book_dir / "book.mobi").write_bytes(b"fake mobi")

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["import", str(scan_dir), "--convert", "--db", str(db_path)],
        )

        assert result.exit_code == 0, result.output
        assert "Skipped 1 MOBI" in result.output
        assert "EPUB exists" in result.output
        # The EPUB should still be cataloged
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        records = catalog.list_all()
        assert len(records) == 1
        conn.close()

    def test_import_convert_processes_mobi_without_epub(
        self, sample_epub: Path, tmp_path: Path,
    ) -> None:
        """MOBI alone in dir + --convert → MOBI converted normally."""
        scan_dir = tmp_path / "scan"
        mobi_dir = scan_dir / "Author" / "MobiOnly"
        mobi_dir.mkdir(parents=True)
        mobi_file = mobi_dir / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")

        fake_result = ConvertResult(
            source=mobi_file,
            epub_path=sample_epub,
            success=True,
        )

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        with patch(
            "bookery.core.converter.convert_one",
            return_value=fake_result,
        ):
            result = runner.invoke(
                cli,
                ["import", str(scan_dir), "--convert", "--db", str(db_path)],
            )

        assert result.exit_code == 0, result.output
        assert "Converting" in result.output
        assert "book.mobi" in result.output
        # Should NOT show dedup skip message
        assert "EPUB exists" not in result.output


class TestImportMetadataDedupCli:
    """E2E tests for metadata-level dedup in CLI output."""

    def test_metadata_dup_shows_skip_reason(self, tmp_path: Path) -> None:
        """Two EPUBs with same title+author → second skipped with reason."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        _make_epub_unique(
            scan_dir / "rose_v1.epub", "The Name of the Rose",
            "Umberto Eco", content_marker="v1",
        )
        _make_epub_unique(
            scan_dir / "rose_v2.epub", "The Name of the Rose",
            "Umberto Eco", content_marker="v2",
        )

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["import", str(scan_dir), "--db", str(db_path)],
        )

        assert result.exit_code == 0, result.output
        assert "1 added" in result.output.lower()
        assert "1 skipped" in result.output.lower()
        assert "title+author" in result.output.lower()

    def test_force_duplicates_flag_imports_dups(self, tmp_path: Path) -> None:
        """--force-duplicates imports metadata dups with warning."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        _make_epub_unique(
            scan_dir / "rose_v1.epub", "The Name of the Rose",
            "Umberto Eco", content_marker="v1",
        )
        _make_epub_unique(
            scan_dir / "rose_v2.epub", "The Name of the Rose",
            "Umberto Eco", content_marker="v2",
        )

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(
            cli, [
                "import", str(scan_dir), "--db", str(db_path),
                "--force-duplicates",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "2 added" in result.output.lower()
        assert "1 forced" in result.output.lower()

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        records = catalog.list_all()
        assert len(records) == 2
        conn.close()

    def test_summary_breakdown_hash_and_metadata(self, tmp_path: Path) -> None:
        """Summary shows breakdown when both hash and metadata skips occur."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        epub1 = _make_epub_unique(
            scan_dir / "rose_v1.epub", "The Name of the Rose",
            "Umberto Eco", content_marker="v1",
        )
        _make_epub_unique(
            scan_dir / "rose_v2.epub", "The Name of the Rose",
            "Umberto Eco", content_marker="v2",
        )
        # Byte-identical copy → hash dup
        shutil.copy(epub1, scan_dir / "rose_copy.epub")

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["import", str(scan_dir), "--db", str(db_path)],
        )

        assert result.exit_code == 0, result.output
        assert "1 added" in result.output.lower()
        assert "2 skipped" in result.output.lower()
        # Summary should contain breakdown info
        assert "hash" in result.output.lower()
        assert "title+author" in result.output.lower()

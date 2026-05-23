# ABOUTME: End-to-end tests for the `bookery prune` CLI command.
# ABOUTME: Covers dry-run preview, -y deletion + FK cascade, and source-vs-output check matrix.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


def _seed_book(
    db_path: Path,
    *,
    title: str,
    file_hash: str,
    source_path: Path,
    output_path: Path | None,
) -> int:
    """Insert a row pointing at the given source/output paths.

    Caller decides whether each path is on disk — this helper only writes
    the catalog row.
    """
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    book_id = catalog.add_book(
        BookMetadata(
            title=title,
            authors=["Test Author"],
            source_path=source_path,
        ),
        file_hash=file_hash,
        output_path=output_path,
    )
    conn.close()
    return book_id


class TestPruneDryRun:
    def test_default_invocation_is_dry_run_and_renders_table(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        library_root = tmp_path / "library"
        library_root.mkdir()

        # One healthy book on disk.
        healthy_src = library_root / "healthy_src.epub"
        healthy_src.write_bytes(b"src")
        healthy_out = library_root / "healthy_out.epub"
        healthy_out.write_bytes(b"out")
        healthy_id = _seed_book(
            db_path,
            title="Healthy",
            file_hash="hh",
            source_path=healthy_src,
            output_path=healthy_out,
        )

        # One orphan: both paths missing.
        orphan_id = _seed_book(
            db_path,
            title="Orphan",
            file_hash="ho",
            source_path=library_root / "gone_src.epub",
            output_path=library_root / "gone_out.epub",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["prune", "--db", str(db_path)])

        assert result.exit_code == 0, result.output
        assert str(orphan_id) in result.output
        assert "Orphan" in result.output
        assert "dry-run" in result.output.lower()

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        assert catalog.get_by_id(orphan_id) is not None
        assert catalog.get_by_id(healthy_id) is not None
        conn.close()

    def test_dry_run_and_yes_are_mutually_exclusive(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        open_library(db_path).close()

        runner = CliRunner()
        result = runner.invoke(
            cli, ["prune", "--dry-run", "-y", "--db", str(db_path)]
        )

        assert result.exit_code != 0
        out_lower = result.output.lower()
        assert "mutually exclusive" in out_lower or "cannot" in out_lower


class TestPruneSourceMissingOutputPresent:
    def test_source_gone_output_present_warns_and_keeps_row(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        library_root = tmp_path / "library"
        library_root.mkdir()

        output_path = library_root / "present_out.epub"
        output_path.write_bytes(b"out")
        book_id = _seed_book(
            db_path,
            title="Half Orphan",
            file_hash="hp",
            source_path=library_root / "gone_src.epub",
            output_path=output_path,
        )

        runner = CliRunner()
        result = runner.invoke(
            cli, ["prune", "--check", "both", "-y", "--db", str(db_path)]
        )

        assert result.exit_code == 0, result.output
        out_lower = result.output.lower()
        assert "warn" in out_lower or "source" in out_lower

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        assert catalog.get_by_id(book_id) is not None, (
            "row with output present must not be deleted"
        )
        conn.close()


class TestPruneDelete:
    def test_both_missing_with_yes_deletes_row_and_cascades(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        library_root = tmp_path / "library"
        library_root.mkdir()

        book_id = _seed_book(
            db_path,
            title="Doomed",
            file_hash="hd",
            source_path=library_root / "gone_src.epub",
            output_path=library_root / "gone_out.epub",
        )

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.add_tag(book_id, "favorites")
        catalog.add_genre(book_id, "Fantasy")
        catalog.update_book(book_id, source="user", publisher="Acme")
        assert conn.execute(
            "SELECT COUNT(*) FROM book_tags WHERE book_id = ?", (book_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM book_genres WHERE book_id = ?", (book_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM book_field_provenance WHERE book_id = ?", (book_id,)
        ).fetchone()[0] >= 1
        conn.close()

        runner = CliRunner()
        result = runner.invoke(
            cli, ["prune", "--check", "both", "-y", "--db", str(db_path)]
        )

        assert result.exit_code == 0, result.output

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        assert catalog.get_by_id(book_id) is None
        assert conn.execute(
            "SELECT COUNT(*) FROM book_tags WHERE book_id = ?", (book_id,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM book_genres WHERE book_id = ?", (book_id,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM book_field_provenance WHERE book_id = ?", (book_id,)
        ).fetchone()[0] == 0
        conn.close()

    def test_summary_line_reports_deletion_count(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        library_root = tmp_path / "library"
        library_root.mkdir()

        _seed_book(
            db_path,
            title="DoomedA",
            file_hash="ha",
            source_path=library_root / "a_src.epub",
            output_path=library_root / "a_out.epub",
        )
        _seed_book(
            db_path,
            title="DoomedB",
            file_hash="hb",
            source_path=library_root / "b_src.epub",
            output_path=library_root / "b_out.epub",
        )

        runner = CliRunner()
        result = runner.invoke(
            cli, ["prune", "--check", "both", "-y", "--db", str(db_path)]
        )

        assert result.exit_code == 0, result.output
        assert "2" in result.output


class TestPruneCheckFlag:
    def test_check_output_ignores_missing_source(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        library_root = tmp_path / "library"
        library_root.mkdir()

        output_path = library_root / "out.epub"
        output_path.write_bytes(b"out")
        book_id = _seed_book(
            db_path,
            title="OutputOnly",
            file_hash="ho2",
            source_path=library_root / "gone.epub",
            output_path=output_path,
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["prune", "--check", "output", "-y", "--db", str(db_path)],
        )

        assert result.exit_code == 0, result.output

        conn = open_library(db_path)
        assert LibraryCatalog(conn).get_by_id(book_id) is not None
        conn.close()


class TestPruneHelp:
    def test_help_lists_prune(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "prune" in result.output

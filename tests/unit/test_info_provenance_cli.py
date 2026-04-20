# ABOUTME: CLI tests for `bookery info --provenance`, --set, --lock, --unlock.
# ABOUTME: Ensures user edits record provenance and locked fields survive rematch.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


def _seed(tmp_path: Path) -> Path:
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


def test_info_provenance_shows_table(tmp_path: Path) -> None:
    db_path = _seed(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["info", "1", "--db", str(db_path), "--provenance"]
    )
    assert result.exit_code == 0, result.output
    assert "Provenance" in result.output
    assert "title" in result.output
    assert "extracted" in result.output


def test_info_set_records_user_provenance_without_locking(tmp_path: Path) -> None:
    db_path = _seed(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["info", "1", "--db", str(db_path), "--set", "title=My Dune"],
    )
    assert result.exit_code == 0, result.output

    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    record = catalog.get_by_id(1)
    assert record is not None
    assert record.metadata.title == "My Dune"
    prov = catalog.get_provenance(1)
    assert prov["title"].source == "user"
    # --set no longer implies --lock; callers opt into locking explicitly.
    assert prov["title"].locked is False
    conn.close()


def test_info_set_and_lock_combined(tmp_path: Path) -> None:
    db_path = _seed(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "info", "1", "--db", str(db_path),
            "--set", "title=My Dune",
            "--lock", "title",
        ],
    )
    assert result.exit_code == 0, result.output

    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    prov = catalog.get_provenance(1)
    assert prov["title"].source == "user"
    assert prov["title"].locked is True
    conn.close()


def test_info_set_allows_value_containing_equals(tmp_path: Path) -> None:
    db_path = _seed(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "info", "1", "--db", str(db_path),
            "--set", "description=a=b",
        ],
    )
    assert result.exit_code == 0, result.output

    conn = open_library(db_path)
    record = LibraryCatalog(conn).get_by_id(1)
    assert record is not None
    assert record.metadata.description == "a=b"
    conn.close()


def test_info_unlock_removes_lock(tmp_path: Path) -> None:
    db_path = _seed(tmp_path)
    runner = CliRunner()
    runner.invoke(
        cli,
        ["info", "1", "--db", str(db_path), "--lock", "title"],
    )
    runner.invoke(
        cli,
        ["info", "1", "--db", str(db_path), "--unlock", "title"],
    )

    conn = open_library(db_path)
    locked = LibraryCatalog(conn).get_locked_fields(1)
    assert "title" not in locked
    conn.close()


def test_info_set_rejects_unknown_field(tmp_path: Path) -> None:
    db_path = _seed(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "info", "1", "--db", str(db_path),
            "--set", "bogus=x",
        ],
    )
    assert result.exit_code != 0
    assert "Unknown field" in result.output

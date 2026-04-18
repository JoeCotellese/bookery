# ABOUTME: Tests for scripts/migrate_to_library_root.py — planning and execution.
# ABOUTME: Covers dry-run planning, idempotency, missing files, and collision handling.

import importlib.util
import sys as _sys
from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata

_SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "migrate_to_library_root.py"
_spec = importlib.util.spec_from_file_location("migrate_to_library_root", _SCRIPT_PATH)
assert _spec and _spec.loader
migrate = importlib.util.module_from_spec(_spec)
_sys.modules["migrate_to_library_root"] = migrate
_spec.loader.exec_module(migrate)  # type: ignore[union-attr]


def _make_book(tmp_path: Path, title: str, _author: str, hash_prefix: str) -> Path:
    """Create a minimal 'epub' file on disk and return its path."""
    path = tmp_path / f"{hash_prefix}_{title}.epub"
    path.write_bytes(b"fake epub content " + hash_prefix.encode())
    return path


def _add(catalog: LibraryCatalog, source: Path, title: str, author: str, file_hash: str) -> int:
    metadata = BookMetadata(
        title=title,
        authors=[author],
        author_sort=None,
        source_path=source,
    )
    return catalog.add_book(metadata, file_hash=file_hash)


@pytest.fixture
def library(tmp_path):
    db_path = tmp_path / "test.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    yield conn, catalog, tmp_path
    conn.close()


def test_plan_actions_classifies_missing_source(library):
    _conn, catalog, tmp_path = library
    # Create then delete the source to simulate a dangling row
    src = _make_book(tmp_path, "Gone", "Ghost Writer", "h1")
    _add(catalog, src, "Gone", "Ghost Writer", "h1")
    src.unlink()

    actions = migrate.plan_actions(
        catalog.list_all(),
        library_root=tmp_path / "lib",
        legacy_cwd=tmp_path,
    )
    assert len(actions) == 1
    assert actions[0].reason == "missing-source"
    assert actions[0].current is None


def test_plan_actions_picks_correct_target(library):
    _conn, catalog, tmp_path = library
    src = _make_book(tmp_path, "Foundation", "Isaac Asimov", "h2")
    _add(catalog, src, "Foundation", "Isaac Asimov", "h2")
    library_root = tmp_path / "lib"

    actions = migrate.plan_actions(
        catalog.list_all(), library_root=library_root, legacy_cwd=tmp_path
    )
    assert len(actions) == 1
    assert actions[0].reason == "ok"
    assert actions[0].target == library_root / "Asimov, Isaac" / "Foundation.epub"


def test_plan_actions_handles_collisions(library):
    _conn, catalog, tmp_path = library
    src1 = _make_book(tmp_path, "Foundation", "Isaac Asimov", "h3")
    src2 = _make_book(tmp_path, "Foundation2", "Isaac Asimov", "h4")
    _add(catalog, src1, "Foundation", "Isaac Asimov", "h3")
    # Second book also resolves to "Foundation.epub" after sanitize
    _add(catalog, src2, "Foundation", "Isaac Asimov", "h4")

    library_root = tmp_path / "lib"
    actions = migrate.plan_actions(
        catalog.list_all(), library_root=library_root, legacy_cwd=tmp_path
    )
    targets = {a.target for a in actions}
    assert len(targets) == 2, "collisions must get unique names within the plan"


def test_plan_actions_detects_already_at_target(library):
    _conn, catalog, tmp_path = library
    # Pre-create the organized layout
    library_root = tmp_path / "lib"
    organized = library_root / "Asimov, Isaac" / "Foundation.epub"
    organized.parent.mkdir(parents=True)
    organized.write_bytes(b"already there")

    # Catalog the book with its source_path pointing at the organized location
    _add(catalog, organized, "Foundation", "Isaac Asimov", "h5")

    actions = migrate.plan_actions(
        catalog.list_all(), library_root=library_root, legacy_cwd=tmp_path
    )
    assert actions[0].reason == "already-at-target"


def test_execute_copies_and_updates_db(library):
    conn, catalog, tmp_path = library
    src = _make_book(tmp_path, "Foundation", "Isaac Asimov", "h6")
    book_id = _add(catalog, src, "Foundation", "Isaac Asimov", "h6")
    library_root = tmp_path / "lib"

    actions = migrate.plan_actions(
        catalog.list_all(), library_root=library_root, legacy_cwd=tmp_path
    )
    log_file = tmp_path / "migration.log"
    counts = migrate.execute_actions(actions, catalog, conn, log_file)

    assert counts["ok"] == 1
    # File copied to target
    target = library_root / "Asimov, Isaac" / "Foundation.epub"
    assert target.exists()
    # Original preserved (copy, not move)
    assert src.exists()
    # DB updated with absolute path
    record = catalog.get_by_id(book_id)
    assert record is not None
    assert record.output_path == target
    # Log written
    assert "ok" in log_file.read_text()


def test_execute_is_idempotent(library):
    conn, catalog, tmp_path = library
    src = _make_book(tmp_path, "Foundation", "Isaac Asimov", "h7")
    _add(catalog, src, "Foundation", "Isaac Asimov", "h7")
    library_root = tmp_path / "lib"
    log_file = tmp_path / "migration.log"

    # First run
    actions1 = migrate.plan_actions(
        catalog.list_all(), library_root=library_root, legacy_cwd=tmp_path
    )
    migrate.execute_actions(actions1, catalog, conn, log_file)

    # Second run — everything should now be "already-at-target"
    # The DB's output_path is set to the target, so current_location returns the target.
    actions2 = migrate.plan_actions(
        catalog.list_all(), library_root=library_root, legacy_cwd=tmp_path
    )
    assert all(a.reason == "already-at-target" for a in actions2)


def test_legacy_relative_output_path_resolves(library):
    """Legacy relative output_path (bookery-output/...) must resolve via legacy_cwd."""
    conn, catalog, tmp_path = library
    # Simulate the legacy CWD layout
    legacy_cwd = tmp_path / "legacy_project"
    legacy_cwd.mkdir()
    legacy_output = legacy_cwd / "bookery-output" / "Asimov, Isaac" / "Foundation.epub"
    legacy_output.parent.mkdir(parents=True)
    legacy_output.write_bytes(b"legacy data")

    # Source file that no longer exists
    missing_src = tmp_path / "missing.epub"
    missing_src.write_bytes(b"x")
    book_id = _add(catalog, missing_src, "Foundation", "Isaac Asimov", "h8")
    missing_src.unlink()

    # Write a legacy relative output_path into the DB
    conn.execute(
        "UPDATE books SET output_path = ? WHERE id = ?",
        ("bookery-output/Asimov, Isaac/Foundation.epub", book_id),
    )
    conn.commit()

    library_root = tmp_path / "lib"
    actions = migrate.plan_actions(
        catalog.list_all(), library_root=library_root, legacy_cwd=legacy_cwd
    )
    assert actions[0].reason == "ok"
    assert actions[0].current == legacy_output.resolve()

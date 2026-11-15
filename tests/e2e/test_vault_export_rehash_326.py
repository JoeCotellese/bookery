# ABOUTME: Acceptance test for #326: re-running vault-export over the same library file.
# ABOUTME: The existing catalog row must pick up the new file's hash instead of going stale.

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.hashing import compute_file_hash

pytestmark = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")

FIXTURE = Path(__file__).parent.parent / "fixtures" / "vault"
OLD_MODIFIED = "2000-01-01T00:00:00"


def _export(vault: Path, db: Path):
    return CliRunner().invoke(
        cli,
        [
            "vault-export",
            "--vault",
            str(vault),
            "--title",
            "Test Vault",
            "--author",
            "Test Author",
            # Pin the folders so a developer's real config cannot filter the vault.
            "--include-folder",
            "3_Permanent Notes",
            "--include-folder",
            "2_Literature Notes",
            "--catalog",
            "--db",
            str(db),
        ],
        catch_exceptions=False,
    )


def test_ac1_reexport_refreshes_existing_row_hash(
    tmp_path: Path,
    _isolate_library_root: Path,
) -> None:
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURE, vault)
    db = tmp_path / "library.db"

    first = _export(vault, db)
    assert first.exit_code == 0, first.output

    output = _isolate_library_root / "Test Vault.epub"
    assert output.exists()

    conn = open_library(db)
    try:
        records = LibraryCatalog(conn).list_all()
        assert len(records) == 1, [r.metadata.title for r in records]
        row_id = records[0].id
        old_hash = records[0].file_hash
        # Backdate so the assertion below does not depend on wall-clock seconds.
        conn.execute("UPDATE books SET date_modified = ? WHERE id = ?", (OLD_MODIFIED, row_id))
        conn.commit()
    finally:
        conn.close()

    # Change the vault so the second export produces different bytes.
    (vault / "3_Permanent Notes" / "added-after-first-export.md").write_text(
        "# Added After First Export\n\nThis note changes the EPUB contents.\n"
    )

    second = _export(vault, db)
    assert second.exit_code == 0, second.output

    new_hash = compute_file_hash(output)
    assert new_hash != old_hash, "the vault edit should change the exported bytes"

    conn = open_library(db)
    try:
        records = LibraryCatalog(conn).list_all()
    finally:
        conn.close()

    assert len(records) == 1, [r.metadata.title for r in records]
    record = records[0]
    assert record.id == row_id
    assert record.file_hash == new_hash
    assert record.date_modified > OLD_MODIFIED

    # The run must say the row was updated, not that the export was skipped.
    assert "skipped" not in second.output.lower(), second.output
    assert "updated" in second.output.lower(), second.output

# ABOUTME: Integration tests for scripts/migrate_strip_description_html.py.
# ABOUTME: Verifies HTML cleanup is correct, idempotent, and leaves clean rows alone.

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from bookery.db.connection import open_library

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "migrate_strip_description_html.py"
)


def _load_script_module():
    """Import the standalone script as a module for direct function calls."""
    spec = importlib.util.spec_from_file_location("_migrate_strip_description_html", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migrate():
    return _load_script_module().migrate


@pytest.fixture
def db_path(tmp_path):
    """Real bookery library with a couple of seeded book rows."""
    path = tmp_path / "library.db"
    # open_library applies all schema migrations against a fresh sqlite file.
    conn = open_library(path, check_same_thread=False)
    conn.executemany(
        "INSERT INTO books (title, source_path, file_hash, description) VALUES (?, ?, ?, ?)",
        [
            ("With HTML", "/books/1.epub", "hash1", '<p class="description">A &amp; B</p>'),
            ("Plain Text", "/books/2.epub", "hash2", "Already clean."),
            ("Null Desc", "/books/3.epub", "hash3", None),
            ("Multi Para", "/books/4.epub", "hash4", "<p>first</p><p>second</p>"),
        ],
    )
    conn.commit()
    conn.close()
    return path


def _descriptions(db_path: Path) -> dict[str, str | None]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT title, description FROM books ORDER BY id").fetchall()
        return {title: desc for title, desc in rows}
    finally:
        conn.close()


def test_migrate_strips_html_from_existing_rows(migrate, db_path):
    count = migrate(db_path)
    assert count == 2  # the two HTML rows; plain and null are untouched.
    descs = _descriptions(db_path)
    assert descs["With HTML"] == "A & B"
    assert descs["Plain Text"] == "Already clean."
    assert descs["Null Desc"] is None
    assert descs["Multi Para"] == "first\n\nsecond"


def test_migrate_is_idempotent(migrate, db_path):
    first = migrate(db_path)
    second = migrate(db_path)
    assert first == 2
    # Second pass: nothing to do — all rows are already plain text.
    assert second == 0
    descs = _descriptions(db_path)
    assert descs["With HTML"] == "A & B"
    assert descs["Multi Para"] == "first\n\nsecond"


def test_migrate_dry_run_does_not_write(migrate, db_path):
    before = _descriptions(db_path)
    count = migrate(db_path, dry_run=True)
    after = _descriptions(db_path)
    assert count == 2
    assert before == after  # dry-run preserves the original strings.

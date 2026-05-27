# ABOUTME: SQLite database connection management for the Bookery library catalog.
# ABOUTME: Opens or creates the database, applies schema, and provides connection context.

import json
import sqlite3
from pathlib import Path

from bookery.core.text_sort import compute_author_sort
from bookery.db.schema import MIGRATIONS, SCHEMA_V1

DEFAULT_DB_PATH = Path.home() / ".bookery" / "library.db"


def _author_sort_from_json(authors_json: str | None) -> str:
    """SQLite UDF: derive an author sort key from a stored authors-JSON cell.

    Used by the V10 backfill to express the same "Last, First Middle"
    inversion rule that `compute_author_sort` enforces on the Python write
    path. Gracefully handles NULL / empty / malformed JSON so the migration
    can be run against any historical row shape — bad rows fall back to
    "Unknown" rather than aborting the entire migration.
    """
    if not authors_json:
        return "Unknown"
    try:
        authors = json.loads(authors_json)
    except (TypeError, ValueError):
        return "Unknown"
    if not isinstance(authors, list):
        return "Unknown"
    return compute_author_sort([str(a) for a in authors])


def _schema_exists(conn: sqlite3.Connection) -> bool:
    """Check if the schema has already been applied."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    return cursor.fetchone() is not None


def _apply_schema(conn: sqlite3.Connection) -> None:
    """Execute the DDL to create all tables, indexes, and triggers."""
    conn.executescript(SCHEMA_V1)


def _get_schema_version(conn: sqlite3.Connection) -> int:
    """Read the current schema version from the database."""
    cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
    row = cursor.fetchone()
    return row[0] if row else 0


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply pending schema migrations sequentially.

    Reads the current schema version and applies any migrations with a higher
    version number. No-op if the database is already at the latest version.
    """
    current = _get_schema_version(conn)
    for version, sql in MIGRATIONS:
        if version > current:
            conn.executescript(sql)


def open_library(
    path: Path | None = None,
    *,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    """Open or create the Bookery library database.

    Creates the database file and parent directories if they don't exist.
    Applies the schema on first creation. Sets WAL journal mode and
    sqlite3.Row factory for dict-like column access.

    Args:
        path: Path to the database file. Defaults to ~/.bookery/library.db.
        check_same_thread: If False, allow connection use across threads.
            Set to False for web servers where requests run on worker threads.

    Returns:
        A configured sqlite3.Connection.
    """
    db_path = path or DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Register the JSON-aware author-sort UDF so SCHEMA_V10's backfill can call
    # it from raw SQL. Registered before migrations run; left in place after
    # so any future migration (or ad-hoc query) can reuse it.
    conn.create_function("bookery_author_sort_from_json", 1, _author_sort_from_json)

    if not _schema_exists(conn):
        _apply_schema(conn)

    _apply_migrations(conn)

    return conn

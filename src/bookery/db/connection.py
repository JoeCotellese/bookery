# ABOUTME: SQLite database connection management for the Bookery library catalog.
# ABOUTME: Opens or creates the database, applies schema, and provides connection context.

import sqlite3
from pathlib import Path

from bookery.db.schema import MIGRATIONS, SCHEMA_V1

DEFAULT_DB_PATH = Path.home() / ".bookery" / "library.db"


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


def open_library(path: Path | None = None) -> sqlite3.Connection:
    """Open or create the Bookery library database.

    Creates the database file and parent directories if they don't exist.
    Applies the schema on first creation. Sets WAL journal mode and
    sqlite3.Row factory for dict-like column access.

    Args:
        path: Path to the database file. Defaults to ~/.bookery/library.db.

    Returns:
        A configured sqlite3.Connection.
    """
    db_path = path or DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    if not _schema_exists(conn):
        _apply_schema(conn)

    _apply_migrations(conn)

    return conn

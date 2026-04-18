# ABOUTME: SQLite-backed cache that maps (source EPUB hash, kepubify version) to kepub hash.
# ABOUTME: Lets `bookery sync kobo` skip kepubify invocations when on-device files already match.

import sqlite3
from contextlib import closing
from pathlib import Path


class KepubCache:
    """Persistent cache of kepub hashes keyed on (source_hash, kepubify_version)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS kepub_entries ("
                "  source_hash TEXT NOT NULL,"
                "  kepubify_version TEXT NOT NULL,"
                "  kepub_sha TEXT NOT NULL,"
                "  PRIMARY KEY (source_hash, kepubify_version)"
                ")"
            )
            conn.commit()

    def get(self, source_hash: str, kepubify_version: str) -> str | None:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                "SELECT kepub_sha FROM kepub_entries "
                "WHERE source_hash = ? AND kepubify_version = ?",
                (source_hash, kepubify_version),
            ).fetchone()
        return row[0] if row else None

    def put(self, source_hash: str, kepubify_version: str, kepub_sha: str) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kepub_entries "
                "(source_hash, kepubify_version, kepub_sha) VALUES (?, ?, ?)",
                (source_hash, kepubify_version, kepub_sha),
            )
            conn.commit()

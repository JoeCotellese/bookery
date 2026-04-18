# ABOUTME: SQLite-backed cache that maps (source EPUB hash, kepubify version) to kepub hash.
# ABOUTME: Lets `bookery sync kobo` skip kepubify invocations when on-device files already match.

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KepubCacheEntry:
    source_hash: str
    kepubify_version: str
    kepub_sha: str
    device_path: Path


class KepubCache:
    """Persistent cache of kepub hashes keyed on (source_hash, kepubify_version).

    Also records the device-side path each kepub was written to, which a
    future `bookery sync kobo --prune` will use to walk and delete only
    files we actually wrote.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS kepub_entries ("
                "  source_hash TEXT NOT NULL,"
                "  kepubify_version TEXT NOT NULL,"
                "  kepub_sha TEXT NOT NULL,"
                "  device_path TEXT NOT NULL,"
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

    def put(
        self,
        source_hash: str,
        kepubify_version: str,
        kepub_sha: str,
        device_path: Path,
    ) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kepub_entries "
                "(source_hash, kepubify_version, kepub_sha, device_path) "
                "VALUES (?, ?, ?, ?)",
                (source_hash, kepubify_version, kepub_sha, str(device_path)),
            )
            conn.commit()

    def iter_entries(self) -> list[KepubCacheEntry]:
        """Return every cached entry (for `--prune` walks)."""
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                "SELECT source_hash, kepubify_version, kepub_sha, device_path "
                "FROM kepub_entries"
            ).fetchall()
        return [
            KepubCacheEntry(
                source_hash=r[0],
                kepubify_version=r[1],
                kepub_sha=r[2],
                device_path=Path(r[3]),
            )
            for r in rows
        ]

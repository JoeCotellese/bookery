# ABOUTME: SQLite-backed cache for metadata provider HTTP responses.
# ABOUTME: Keyed on (provider, query_type, query_key) with a TTL-based freshness check.

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CachedResponse:
    response: dict[str, Any]
    fetched_at: float


class MetadataCache:
    """Persistent response cache for metadata providers.

    Each row stores a JSON-serialized HTTP response keyed by
    ``(provider, query_type, query_key)``. Entries older than
    ``ttl_seconds`` are treated as missing on read.
    """

    def __init__(self, path: Path, *, ttl_seconds: float) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS metadata_cache ("
                "  provider TEXT NOT NULL,"
                "  query_type TEXT NOT NULL,"
                "  query_key TEXT NOT NULL,"
                "  response_json TEXT NOT NULL,"
                "  fetched_at REAL NOT NULL,"
                "  PRIMARY KEY (provider, query_type, query_key)"
                ")"
            )
            conn.commit()

    def get(
        self, provider: str, query_type: str, query_key: str
    ) -> dict[str, Any] | None:
        """Return the cached response if fresh, otherwise None."""
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                "SELECT response_json, fetched_at FROM metadata_cache "
                "WHERE provider = ? AND query_type = ? AND query_key = ?",
                (provider, query_type, query_key),
            ).fetchone()
        if row is None:
            return None
        response_json, fetched_at = row
        if self.ttl_seconds >= 0 and (time.time() - float(fetched_at)) > self.ttl_seconds:
            return None
        return json.loads(response_json)

    def put(
        self,
        provider: str,
        query_type: str,
        query_key: str,
        response: dict[str, Any],
    ) -> None:
        """Store (or replace) a provider response."""
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO metadata_cache "
                "(provider, query_type, query_key, response_json, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (provider, query_type, query_key, json.dumps(response), time.time()),
            )
            conn.commit()

    def clear(self, provider: str | None = None) -> None:
        """Remove all entries (or all entries for a single provider)."""
        with closing(sqlite3.connect(self.path)) as conn:
            if provider is None:
                conn.execute("DELETE FROM metadata_cache")
            else:
                conn.execute("DELETE FROM metadata_cache WHERE provider = ?", (provider,))
            conn.commit()

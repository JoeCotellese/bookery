# ABOUTME: SQLite-backed cache for LLM classification responses.
# ABOUTME: Key = sha256(prompt_version + model + chunk_text); safe to delete at any time.

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path


def make_key(prompt_version: int, model: str, chunk_text: str) -> str:
    """Derive a stable cache key for a chunk under a given prompt template and model."""
    digest = hashlib.sha256()
    digest.update(str(prompt_version).encode("utf-8"))
    digest.update(b"\x00")
    digest.update(model.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(chunk_text.encode("utf-8"))
    return digest.hexdigest()


class LLMCache:
    """Persistent key/value cache for LLM responses (raw JSON strings)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS llm_cache ("
                "  key TEXT PRIMARY KEY,"
                "  value TEXT NOT NULL"
                ")"
            )
            conn.commit()

    def get(self, key: str) -> str | None:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                "SELECT value FROM llm_cache WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def put(self, key: str, value: str) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()

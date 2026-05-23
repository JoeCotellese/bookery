# ABOUTME: Integration tests for plan-05 — explicit metadata_matched_at signal.
# ABOUTME: Covers schema V7 migration, resume filter, and match-acceptance writes.

import sqlite3
from pathlib import Path

from click.testing import CliRunner

from bookery.cli.commands.rematch_cmd import rematch
from bookery.core.pipeline import MatchOneResult
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import _get_schema_version, open_library
from bookery.db.hashing import compute_file_hash
from bookery.db.schema import (
    SCHEMA_V1,
    SCHEMA_V2,
    SCHEMA_V3,
    SCHEMA_V4,
    SCHEMA_V5,
    SCHEMA_V6,
)
from bookery.metadata.normalizer import NormalizationResult
from bookery.metadata.types import BookMetadata


def _make_v6_db(db_path: Path) -> sqlite3.Connection:
    """Create a database at exactly schema V6 (pre-V7) with no auto-migrate."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_V1)
    conn.executescript(SCHEMA_V2)
    conn.executescript(SCHEMA_V3)
    conn.executescript(SCHEMA_V4)
    conn.executescript(SCHEMA_V5)
    conn.executescript(SCHEMA_V6)
    return conn


class TestMatchedSignal:
    """Plan-05 step 1+2: explicit metadata_matched_at signal."""

    def test_schema_v7_adds_metadata_matched_at_column(self, tmp_path: Path) -> None:
        """Opening a fresh DB lands at V7 with metadata_matched_at present."""
        db_path = tmp_path / "fresh.db"
        conn = open_library(db_path)
        try:
            assert _get_schema_version(conn) == 7
            cursor = conn.execute("PRAGMA table_info(books)")
            cols = {row["name"] for row in cursor.fetchall()}
            assert "metadata_matched_at" in cols
        finally:
            conn.close()

    def test_v7_migration_backfills_rows_with_provider_identifiers(
        self, tmp_path: Path,
    ) -> None:
        """Mixed V6 fixture: only rows with provider ids in identifiers get a ts."""
        db_path = tmp_path / "mixed.db"
        conn = _make_v6_db(db_path)

        # Row A: openlibrary_work identifier — should be backfilled
        conn.execute(
            "INSERT INTO books (title, authors, identifiers, source_path, file_hash, "
            "date_modified) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "Has OL Work",
                '["Author"]',
                '{"openlibrary_work": "/works/OL1W"}',
                "/a.epub",
                "hash-a",
                "2025-01-01T00:00:00",
            ),
        )
        # Row B: googlebooks_volume — should be backfilled
        conn.execute(
            "INSERT INTO books (title, authors, identifiers, source_path, file_hash, "
            "date_modified) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "Has Google Vol",
                '["Author"]',
                '{"googlebooks_volume": "abc123"}',
                "/b.epub",
                "hash-b",
                "2025-02-02T00:00:00",
            ),
        )
        # Row C: an isbn_10 key — should be backfilled
        conn.execute(
            "INSERT INTO books (title, authors, identifiers, source_path, file_hash, "
            "date_modified) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "Has ISBN id",
                '["Author"]',
                '{"isbn_10": "0123456789"}',
                "/c.epub",
                "hash-c",
                "2025-03-03T00:00:00",
            ),
        )
        # Row D: no provider identifiers at all — should stay NULL
        conn.execute(
            "INSERT INTO books (title, authors, identifiers, source_path, file_hash, "
            "date_modified) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "Bare row",
                '["Author"]',
                "{}",
                "/d.epub",
                "hash-d",
                "2025-04-04T00:00:00",
            ),
        )
        # Row E: null identifiers — stays NULL
        conn.execute(
            "INSERT INTO books (title, authors, identifiers, source_path, file_hash, "
            "date_modified) VALUES (?, ?, NULL, ?, ?, ?)",
            (
                "Null ids",
                '["Author"]',
                "/e.epub",
                "hash-e",
                "2025-05-05T00:00:00",
            ),
        )
        conn.commit()
        conn.close()

        # Reopen to trigger V7 migration
        conn = open_library(db_path)
        try:
            assert _get_schema_version(conn) == 7
            rows = conn.execute(
                "SELECT title, metadata_matched_at FROM books ORDER BY title"
            ).fetchall()
            ts = {r["title"]: r["metadata_matched_at"] for r in rows}

            assert ts["Has OL Work"] == "2025-01-01T00:00:00"
            assert ts["Has Google Vol"] == "2025-02-02T00:00:00"
            assert ts["Has ISBN id"] == "2025-03-03T00:00:00"
            assert ts["Bare row"] is None
            assert ts["Null ids"] is None
        finally:
            conn.close()

    def test_set_matched_at_writes_timestamp(self, tmp_path: Path) -> None:
        """LibraryCatalog exposes a way to set metadata_matched_at."""
        db_path = tmp_path / "catalog.db"
        conn = open_library(db_path)
        try:
            catalog = LibraryCatalog(conn)
            book_id = catalog.add_book(
                BookMetadata(title="T", authors=["A"], source_path=Path("/x.epub")),
                file_hash="h1",
            )

            before = catalog.get_by_id(book_id)
            assert before is not None
            assert before.metadata_matched_at is None

            catalog.set_matched_at(book_id, "2026-05-23T10:00:00")
            after = catalog.get_by_id(book_id)
            assert after is not None
            assert after.metadata_matched_at == "2026-05-23T10:00:00"
        finally:
            conn.close()

    def test_rematch_resume_skips_matched_rows(
        self, tmp_path: Path, sample_epub: Path, monkeypatch,
    ) -> None:
        """rematch --resume now keys off metadata_matched_at, not output_path."""
        db_path = tmp_path / "resume.db"
        conn = open_library(db_path)
        try:
            catalog = LibraryCatalog(conn)
            # Matched row: has metadata_matched_at set, even though
            # output_path is also set (canonical-library scenario).
            metadata = BookMetadata(
                title="Already Matched",
                authors=["Eco"],
                source_path=sample_epub,
            )
            file_hash = compute_file_hash(sample_epub)
            book_id = catalog.add_book(
                metadata, file_hash=file_hash, output_path=sample_epub,
            )
            catalog.set_matched_at(book_id, "2026-05-01T00:00:00")
        finally:
            conn.close()

        called: list[int] = []

        def fake_match_one(*_args, **_kwargs):  # pragma: no cover - guard
            called.append(1)
            return MatchOneResult(status="skipped")

        monkeypatch.setattr(
            "bookery.cli.commands.rematch_cmd.match_one", fake_match_one,
        )
        class _StubProvider:
            def lookup_by_url(self, url):  # pragma: no cover - guard
                return None

        monkeypatch.setattr(
            "bookery.cli.commands.rematch_cmd._create_provider",
            lambda use_cache=True: _StubProvider(),
        )

        runner = CliRunner()
        result = runner.invoke(
            rematch,
            ["--all", "--db", str(db_path), "--yes", "-o", str(tmp_path / "out")],
        )
        assert result.exit_code == 0, result.output
        assert called == []
        assert "already matched" in result.output.lower()

    def test_rematch_resume_reprocesses_unmatched_rows(
        self, tmp_path: Path, sample_epub: Path, monkeypatch,
    ) -> None:
        """An unmatched row (no metadata_matched_at) IS reprocessed on --resume."""
        db_path = tmp_path / "resume2.db"
        conn = open_library(db_path)
        try:
            catalog = LibraryCatalog(conn)
            metadata = BookMetadata(
                title="Needs Match",
                authors=["Eco"],
                source_path=sample_epub,
            )
            file_hash = compute_file_hash(sample_epub)
            # output_path IS set (library-canonical) but metadata_matched_at
            # is NOT — so the row should still be reprocessed.
            catalog.add_book(metadata, file_hash=file_hash, output_path=sample_epub)
        finally:
            conn.close()

        called: list[int] = []

        def fake_match_one(*_args, **_kwargs):
            called.append(1)
            return MatchOneResult(status="skipped")

        monkeypatch.setattr(
            "bookery.cli.commands.rematch_cmd.match_one", fake_match_one,
        )
        class _StubProvider:
            def lookup_by_url(self, url):  # pragma: no cover - guard
                return None

        monkeypatch.setattr(
            "bookery.cli.commands.rematch_cmd._create_provider",
            lambda use_cache=True: _StubProvider(),
        )

        runner = CliRunner()
        result = runner.invoke(
            rematch,
            ["--all", "--db", str(db_path), "--yes", "-o", str(tmp_path / "out")],
        )
        assert result.exit_code == 0, result.output
        assert called == [1]

    def test_rematch_writes_matched_at_on_accept(
        self, tmp_path: Path, sample_epub: Path, monkeypatch,
    ) -> None:
        """rematch records metadata_matched_at when match_one returns matched."""
        db_path = tmp_path / "writes.db"
        conn = open_library(db_path)
        try:
            catalog = LibraryCatalog(conn)
            metadata = BookMetadata(
                title="Pre-Match", authors=["Eco"], source_path=sample_epub,
            )
            file_hash = compute_file_hash(sample_epub)
            book_id = catalog.add_book(metadata, file_hash=file_hash)
        finally:
            conn.close()

        out_path = tmp_path / "out" / "x.epub"
        out_path.parent.mkdir(parents=True)
        out_path.write_bytes(b"fake")

        def fake_match_one(*_args, **_kwargs):
            enriched = BookMetadata(
                title="Matched!", authors=["Eco"], language="en",
                identifiers={"openlibrary_work": "/works/OL1W"},
            )
            return MatchOneResult(
                status="matched", metadata=enriched, output_path=out_path,
                normalization=NormalizationResult(
                    original=metadata, normalized=metadata, was_modified=False,
                ),
            )

        monkeypatch.setattr(
            "bookery.cli.commands.rematch_cmd.match_one", fake_match_one,
        )
        class _StubProvider:
            def lookup_by_url(self, url):  # pragma: no cover - guard
                return None

        monkeypatch.setattr(
            "bookery.cli.commands.rematch_cmd._create_provider",
            lambda use_cache=True: _StubProvider(),
        )

        runner = CliRunner()
        result = runner.invoke(
            rematch,
            ["--all", "--db", str(db_path), "--yes", "--no-resume",
             "-o", str(tmp_path / "out")],
        )
        assert result.exit_code == 0, result.output

        conn = open_library(db_path)
        try:
            record = LibraryCatalog(conn).get_by_id(book_id)
            assert record is not None
            assert record.metadata_matched_at is not None
        finally:
            conn.close()

# ABOUTME: Integration tests for plan-05 catalog path-truth invariants:
# ABOUTME: unmatched imports populate output_path (#59), and the explicit
# ABOUTME: metadata_matched_at signal replaces output_path as the matched flag (#64).

import sqlite3
from pathlib import Path

from click.testing import CliRunner
from ebooklib import epub

from bookery.cli.commands.rematch_cmd import rematch
from bookery.core.importer import import_books
from bookery.core.pipeline import MatchOneResult
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import _get_schema_version, open_library
from bookery.db.hashing import compute_file_hash
from bookery.db.schema import (
    LATEST_SCHEMA_VERSION,
    SCHEMA_V1,
    SCHEMA_V2,
    SCHEMA_V3,
    SCHEMA_V4,
    SCHEMA_V5,
    SCHEMA_V6,
)
from bookery.metadata.normalizer import NormalizationResult
from bookery.metadata.types import BookMetadata


def _make_epub(path: Path, title: str, author: str | None = None) -> Path:
    """Create a minimal EPUB for catalog-path-truth checks."""
    book = epub.EpubBook()
    book.set_identifier(f"id-{title}")
    book.set_title(title)
    book.set_language("en")
    if author:
        book.add_author(author)

    chapter = epub.EpubHtml(
        title="Chapter 1",
        file_name="chap01.xhtml",
        lang="en",
    )
    chapter.content = (
        b"<html><body><h1>Chapter 1</h1><p>Content for " + title.encode() + b".</p></body></html>"
    )
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(path), book)
    return path


class TestImporterOutputPath:
    """Lock in the output_path invariant for unmatched imports (issue #59).

    Plan-05 cluster: the importer must always set books.output_path to a real
    file under library_root, even when no match pipeline runs. This guards
    against a future refactor silently leaving output_path NULL, which would
    poison downstream lookups (web UI, sync, vault export).

    A sibling branch (feature/64-matched-signal) may share this file; this
    class is namespaced to keep both PRs mergeable.
    """

    def test_unmatched_import_populates_output_path_under_library_root(
        self,
        tmp_path: Path,
    ) -> None:
        """Importing without --match sets output_path to a real file in library_root."""
        db_path = tmp_path / "lib.db"
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        library_root = tmp_path / "lib"
        library_root.mkdir()

        epub_path = _make_epub(
            source_dir / "rose.epub",
            "The Name of the Rose",
            "Umberto Eco",
        )

        conn = open_library(db_path)
        try:
            catalog = LibraryCatalog(conn)
            result = import_books(
                [epub_path],
                catalog,
                library_root=library_root,
            )

            assert result.added == 1
            assert result.errors == 0

            records = catalog.list_all()
            assert len(records) == 1

            output_path = records[0].output_path
            # Invariant 1: catalog row has output_path populated.
            assert output_path is not None, (
                "unmatched import left output_path NULL — regression on #59"
            )
            # Invariant 2: output_path resolves under library_root.
            resolved_root = library_root.resolve()
            assert output_path.resolve().is_relative_to(resolved_root), (
                f"output_path {output_path} is not under library_root {library_root}"
            )
            # Invariant 3: the file actually exists on disk at output_path.
            assert output_path.exists(), f"output_path {output_path} does not exist on disk"
        finally:
            conn.close()

    def test_unmatched_import_of_multiple_files_all_have_output_paths(
        self,
        tmp_path: Path,
    ) -> None:
        """Every cataloged book from an unmatched batch import has output_path set."""
        db_path = tmp_path / "lib.db"
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        library_root = tmp_path / "lib"
        library_root.mkdir()

        _make_epub(source_dir / "a.epub", "Alpha", "Author A")
        _make_epub(source_dir / "b.epub", "Beta", "Author B")
        _make_epub(source_dir / "c.epub", "Gamma", "Author C")
        paths = sorted(source_dir.glob("*.epub"))

        conn = open_library(db_path)
        try:
            catalog = LibraryCatalog(conn)
            result = import_books(
                paths,
                catalog,
                library_root=library_root,
            )

            assert result.added == 3
            records = catalog.list_all()
            assert len(records) == 3

            resolved_root = library_root.resolve()
            for record in records:
                output_path = record.output_path
                assert output_path is not None, (
                    f"book {record.metadata.title!r} left output_path NULL"
                )
                assert output_path.resolve().is_relative_to(resolved_root)
                assert output_path.exists()
        finally:
            conn.close()


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
            assert _get_schema_version(conn) == LATEST_SCHEMA_VERSION
            cursor = conn.execute("PRAGMA table_info(books)")
            cols = {row["name"] for row in cursor.fetchall()}
            assert "metadata_matched_at" in cols
        finally:
            conn.close()

    def test_v7_migration_backfills_rows_with_provider_provenance(
        self,
        tmp_path: Path,
    ) -> None:
        """V7 backfill is anchored on book_field_provenance, not identifiers JSON.

        The backfill flips ``metadata_matched_at`` on for rows that have at
        least one provenance row whose ``source`` names an actual metadata
        provider (anything other than the internal ``extracted`` / ``user`` /
        ``genres`` sources). This covers every path that recorded a real
        provider write — importer ``--match``, ``rematch``, and the web
        ``enrich_apply`` flow — while excluding rows whose only metadata came
        from EPUB extraction (including Calibre EPUBs that declared an OPF
        ``<dc:identifier opf:scheme="ISBN">`` entry).
        """
        db_path = tmp_path / "mixed.db"
        conn = _make_v6_db(db_path)

        def _insert_book(
            title: str,
            file_hash: str,
            identifiers: str | None,
            date_modified: str,
        ) -> int:
            cursor = conn.execute(
                "INSERT INTO books (title, authors, identifiers, source_path, "
                "file_hash, date_modified) VALUES (?, ?, ?, ?, ?, ?)",
                (title, '["Author"]', identifiers, f"/{file_hash}.epub", file_hash, date_modified),
            )
            return cursor.lastrowid  # type: ignore[return-value]

        def _add_provenance(book_id: int, source: str, field: str = "title") -> None:
            conn.execute(
                "INSERT INTO book_field_provenance (book_id, field_name, source) VALUES (?, ?, ?)",
                (book_id, field, source),
            )

        # Row A: matched via importer --match (openlibrary provider wrote
        # provenance, identifiers JSON also carries a provider key). Should
        # be backfilled.
        a_id = _insert_book(
            "Importer Match",
            "hash-a",
            '{"openlibrary_work": "/works/OL1W"}',
            "2025-01-01T00:00:00",
        )
        _add_provenance(a_id, "openlibrary")

        # Row B: matched via rematch (googlebooks). Should be backfilled.
        b_id = _insert_book(
            "Rematched",
            "hash-b",
            '{"googlebooks_volume": "abc123"}',
            "2025-02-02T00:00:00",
        )
        _add_provenance(b_id, "googlebooks", field="description")

        # Row C: matched via web enrich_apply — provider wrote provenance but
        # NEVER updated the identifiers JSON column. The old heuristic missed
        # these rows entirely; the new backfill catches them.
        c_id = _insert_book(
            "Web Enrich Applied",
            "hash-c",
            "{}",
            "2025-03-03T00:00:00",
        )
        _add_provenance(c_id, "openlibrary", field="title")

        # Row D: EPUB-extraction-only Calibre row whose OPF declared an ISBN
        # scheme. Extraction lowercases that into ``{"isbn": "..."}`` AND
        # writes per-field provenance rows with source='extracted'. This is
        # the false-positive case the old `'%"isbn"%'` LIKE clause hit. The
        # new backfill leaves it NULL.
        d_id = _insert_book(
            "Calibre EPUB With ISBN",
            "hash-d",
            '{"isbn": "9781234567890"}',
            "2025-04-04T00:00:00",
        )
        _add_provenance(d_id, "extracted", field="title")
        _add_provenance(d_id, "extracted", field="authors")

        # Row E: EPUB-extraction-only row with no identifiers at all and only
        # extracted provenance. Stays NULL.
        e_id = _insert_book(
            "Bare EPUB",
            "hash-e",
            "{}",
            "2025-05-05T00:00:00",
        )
        _add_provenance(e_id, "extracted", field="title")

        # Row F: row with only user/genres provenance (manual edits + auto
        # genre applier) but no provider ever ran. Stays NULL.
        f_id = _insert_book(
            "User Edited",
            "hash-f",
            "{}",
            "2025-06-06T00:00:00",
        )
        _add_provenance(f_id, "user", field="title")
        _add_provenance(f_id, "genres", field="primary_genre")

        conn.commit()
        conn.close()

        # Reopen to trigger V7 migration
        conn = open_library(db_path)
        try:
            assert _get_schema_version(conn) == LATEST_SCHEMA_VERSION
            rows = conn.execute(
                "SELECT title, metadata_matched_at FROM books ORDER BY title"
            ).fetchall()
            ts = {r["title"]: r["metadata_matched_at"] for r in rows}

            # Provider-touched rows: backfilled.
            assert ts["Importer Match"] == "2025-01-01T00:00:00"
            assert ts["Rematched"] == "2025-02-02T00:00:00"
            assert ts["Web Enrich Applied"] == "2025-03-03T00:00:00"

            # Extraction-only / user-only rows: stay NULL.
            assert ts["Calibre EPUB With ISBN"] is None
            assert ts["Bare EPUB"] is None
            assert ts["User Edited"] is None
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
        self,
        tmp_path: Path,
        sample_epub: Path,
        monkeypatch,
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
                metadata,
                file_hash=file_hash,
                output_path=sample_epub,
            )
            catalog.set_matched_at(book_id, "2026-05-01T00:00:00")
        finally:
            conn.close()

        called: list[int] = []

        def fake_match_one(*_args, **_kwargs):  # pragma: no cover - guard
            called.append(1)
            return MatchOneResult(status="skipped")

        monkeypatch.setattr(
            "bookery.cli.commands.rematch_cmd.match_one",
            fake_match_one,
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
        self,
        tmp_path: Path,
        sample_epub: Path,
        monkeypatch,
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
            "bookery.cli.commands.rematch_cmd.match_one",
            fake_match_one,
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
        self,
        tmp_path: Path,
        sample_epub: Path,
        monkeypatch,
    ) -> None:
        """rematch records metadata_matched_at when match_one returns matched."""
        db_path = tmp_path / "writes.db"
        conn = open_library(db_path)
        try:
            catalog = LibraryCatalog(conn)
            metadata = BookMetadata(
                title="Pre-Match",
                authors=["Eco"],
                source_path=sample_epub,
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
                title="Matched!",
                authors=["Eco"],
                language="en",
                identifiers={"openlibrary_work": "/works/OL1W"},
            )
            return MatchOneResult(
                status="matched",
                metadata=enriched,
                output_path=out_path,
                normalization=NormalizationResult(
                    original=metadata,
                    normalized=metadata,
                    was_modified=False,
                ),
            )

        monkeypatch.setattr(
            "bookery.cli.commands.rematch_cmd.match_one",
            fake_match_one,
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
            ["--all", "--db", str(db_path), "--yes", "--no-resume", "-o", str(tmp_path / "out")],
        )
        assert result.exit_code == 0, result.output

        conn = open_library(db_path)
        try:
            record = LibraryCatalog(conn).get_by_id(book_id)
            assert record is not None
            assert record.metadata_matched_at is not None
        finally:
            conn.close()

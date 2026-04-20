# ABOUTME: CRUD operations for the Bookery library catalog.
# ABOUTME: Add, query, update, and delete books in the SQLite database.

import json
import sqlite3
from pathlib import Path

from bookery.core.dedup import (
    normalize_author_for_dedup,
    normalize_for_dedup,
    normalize_isbn,
)
from bookery.db.mapping import (
    BookRecord,
    DuplicateMatch,
    ProvenanceEntry,
    metadata_to_row,
    row_to_record,
)
from bookery.metadata.genres import is_canonical_genre
from bookery.metadata.types import BookMetadata


class DuplicateBookError(Exception):
    """Raised when attempting to add a book with a file_hash that already exists."""


class LibraryCatalog:
    """Wraps a sqlite3 connection and provides typed CRUD for the books table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add_book(
        self,
        metadata: BookMetadata,
        file_hash: str,
        output_path: Path | None = None,
        *,
        source: str = "extracted",
    ) -> int:
        """Add a book to the catalog.

        Args:
            metadata: The book's metadata.
            file_hash: SHA-256 hash of the source file.
            output_path: Path to the corrected copy, if any.

        Returns:
            The row ID of the inserted book.

        Raises:
            DuplicateBookError: If a book with this file_hash already exists.
        """
        row = metadata_to_row(metadata, file_hash, output_path)
        columns = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        values = list(row.values())

        try:
            cursor = self._conn.execute(
                f"INSERT INTO books ({columns}) VALUES ({placeholders})",
                values,
            )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed: books.file_hash" in str(exc):
                raise DuplicateBookError(f"Book with hash {file_hash} already exists") from exc
            raise

        book_id = cursor.lastrowid
        assert book_id is not None
        for field_name, value in row.items():
            if field_name in {"source_path", "output_path", "file_hash"}:
                continue
            if value in (None, "", "[]", "{}"):
                continue
            self._upsert_provenance(book_id, field_name, source)

        self._conn.commit()
        return book_id  # type: ignore[return-value]

    def get_by_id(self, book_id: int) -> BookRecord | None:
        """Retrieve a book by its row ID."""
        cursor = self._conn.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        return row_to_record(row) if row else None

    def get_by_hash(self, file_hash: str) -> BookRecord | None:
        """Retrieve a book by its file hash."""
        cursor = self._conn.execute("SELECT * FROM books WHERE file_hash = ?", (file_hash,))
        row = cursor.fetchone()
        return row_to_record(row) if row else None

    def get_by_isbn(self, isbn: str) -> BookRecord | None:
        """Retrieve a book by its ISBN."""
        cursor = self._conn.execute("SELECT * FROM books WHERE isbn = ?", (isbn,))
        row = cursor.fetchone()
        return row_to_record(row) if row else None

    def find_duplicate(self, metadata: BookMetadata) -> DuplicateMatch | None:
        """Check if a book with matching metadata already exists in the catalog.

        Checks ISBN first (highest confidence), then falls back to normalized
        title + author comparison.

        Returns a DuplicateMatch with the existing record and match reason,
        or None if no duplicate found.
        """
        # ISBN check: normalize candidate ISBN and compare against all catalog ISBNs
        if metadata.isbn:
            candidate_isbn = normalize_isbn(metadata.isbn)
            if candidate_isbn:
                cursor = self._conn.execute(
                    "SELECT * FROM books WHERE isbn IS NOT NULL AND isbn != ''",
                )
                for row in cursor.fetchall():
                    existing_isbn = normalize_isbn(row["isbn"])
                    if existing_isbn == candidate_isbn:
                        return DuplicateMatch(
                            record=row_to_record(row),
                            reason="isbn",
                        )

        # Title + author check
        candidate_title = normalize_for_dedup(metadata.title)
        candidate_authors = sorted(normalize_author_for_dedup(a) for a in metadata.authors)

        if not candidate_title or not candidate_authors:
            return None

        cursor = self._conn.execute("SELECT * FROM books")
        for row in cursor.fetchall():
            record = row_to_record(row)
            existing_title = normalize_for_dedup(record.metadata.title)
            existing_authors = sorted(
                normalize_author_for_dedup(a) for a in record.metadata.authors
            )
            if existing_title == candidate_title and existing_authors == candidate_authors:
                return DuplicateMatch(record=record, reason="title_author")

        return None

    def list_all(self) -> list[BookRecord]:
        """Return all books in the catalog, ordered by title."""
        cursor = self._conn.execute("SELECT * FROM books ORDER BY title")
        return [row_to_record(row) for row in cursor.fetchall()]

    def list_all_by_author(self) -> list[BookRecord]:
        """Return all books in the catalog, ordered by author then title."""
        cursor = self._conn.execute("SELECT * FROM books ORDER BY author_sort, title")
        return [row_to_record(row) for row in cursor.fetchall()]

    def list_by_series(self, series: str) -> list[BookRecord]:
        """Return books in a given series, ordered by series_index."""
        cursor = self._conn.execute(
            "SELECT * FROM books WHERE series = ? ORDER BY series_index",
            (series,),
        )
        return [row_to_record(row) for row in cursor.fetchall()]

    def search(self, query: str) -> list[BookRecord]:
        """Full-text search across title, authors, description, and series.

        Uses FTS5 MATCH syntax. Results are ranked by relevance (FTS5 rank).

        Args:
            query: Search terms to match against indexed fields.

        Returns:
            List of matching BookRecords, best matches first.
        """
        cursor = self._conn.execute(
            "SELECT books.* FROM books "
            "JOIN books_fts ON books.id = books_fts.rowid "
            "WHERE books_fts MATCH ? "
            "ORDER BY books_fts.rank",
            (query,),
        )
        return [row_to_record(row) for row in cursor.fetchall()]

    def update_book(
        self,
        book_id: int,
        *,
        source: str | None = None,
        provenance: dict[str, str] | None = None,
        confidence: float | None = None,
        respect_locked: bool = False,
        **fields: object,
    ) -> list[str]:
        """Update one or more fields on a cataloged book.

        Accepts keyword arguments matching books table columns. Authors and
        identifiers values are JSON-serialized automatically. ISBN is
        canonicalized to ISBN-13 on write.

        If ``source`` is provided, a provenance row is written for each
        updated field (credited to that source). ``provenance`` may be
        passed to override the source on a per-field basis.

        If ``respect_locked`` is true, any field with a locked provenance
        row is silently dropped from the update — this is what lets
        ``rematch`` avoid clobbering user-curated values.

        Returns the list of field names that were actually written (after
        locked-field filtering).

        Raises:
            ValueError: If the book_id does not exist.
        """
        if not fields:
            return []

        if respect_locked:
            locked = self.get_locked_fields(book_id)
            fields = {k: v for k, v in fields.items() if k not in locked}
            if not fields:
                return []

        # JSON-serialize list/dict fields
        if "authors" in fields:
            fields["authors"] = json.dumps(fields["authors"])
        if "identifiers" in fields:
            fields["identifiers"] = json.dumps(fields["identifiers"])
        if "subjects" in fields:
            fields["subjects"] = json.dumps(fields["subjects"])
        if fields.get("isbn"):
            isbn_val = fields["isbn"]
            if isinstance(isbn_val, str):
                fields["isbn"] = normalize_isbn(isbn_val) or None

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        set_clause += ", date_modified = strftime('%Y-%m-%dT%H:%M:%S', 'now')"
        values = [*list(fields.values()), book_id]

        cursor = self._conn.execute(
            f"UPDATE books SET {set_clause} WHERE id = ?",
            values,
        )
        if cursor.rowcount == 0:
            self._conn.commit()
            raise ValueError(f"Book with id {book_id} not found")

        written = list(fields.keys())

        if source is not None or provenance:
            # Fields that were cleared to an empty value shouldn't claim a
            # source — the source didn't "supply" a missing value. Delete
            # any stale provenance for those fields and skip the upsert.
            cleared = [k for k in written if fields[k] in (None, "", "[]", "{}")]
            if cleared:
                self._conn.executemany(
                    "DELETE FROM book_field_provenance "
                    "WHERE book_id = ? AND field_name = ?",
                    [(book_id, k) for k in cleared],
                )

            populated = [k for k in written if k not in cleared]
            prov_map = {f: source for f in populated} if source else {}
            if provenance:
                prov_map.update({k: v for k, v in provenance.items() if k in populated})
            prov_map = {k: v for k, v in prov_map.items() if v}
            for field_name, field_source in prov_map.items():
                self._upsert_provenance(
                    book_id,
                    field_name,
                    field_source,
                    confidence=confidence,
                )

        self._conn.commit()

        # Auto-genre hook: only fires when a provider source is attached,
        # so internal bookkeeping (e.g. store_subjects) doesn't clobber
        # the separate genre-apply workflow.
        if (
            source is not None
            and "subjects" in written
            and fields.get("subjects") not in (None, "", "[]")
        ):
            try:
                from bookery.core.genre_applier import auto_apply_for_book
            except ImportError:  # pragma: no cover — defensive
                return written
            try:
                subjects_written = json.loads(fields["subjects"])  # type: ignore[arg-type]
            except (TypeError, ValueError):
                subjects_written = []
            if subjects_written:
                auto_apply_for_book(self, book_id, list(subjects_written))

        return written

    def _upsert_provenance(
        self,
        book_id: int,
        field_name: str,
        source: str,
        *,
        confidence: float | None = None,
    ) -> None:
        """Insert or refresh a provenance row, preserving the locked flag."""
        self._conn.execute(
            """
            INSERT INTO book_field_provenance (book_id, field_name, source, confidence)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(book_id, field_name) DO UPDATE SET
                source = excluded.source,
                confidence = excluded.confidence,
                fetched_at = strftime('%Y-%m-%dT%H:%M:%S', 'now')
            """,
            (book_id, field_name, source, confidence),
        )

    def set_field_lock(self, book_id: int, field_name: str, locked: bool) -> None:
        """Set or clear the locked flag for a field.

        If no provenance row exists for the field yet and we're locking it,
        a ``user`` row is created to anchor the lock.
        """
        if locked:
            self._conn.execute(
                """
                INSERT INTO book_field_provenance (book_id, field_name, source, locked)
                VALUES (?, ?, 'user', 1)
                ON CONFLICT(book_id, field_name) DO UPDATE SET locked = 1
                """,
                (book_id, field_name),
            )
        else:
            self._conn.execute(
                "UPDATE book_field_provenance SET locked = 0 "
                "WHERE book_id = ? AND field_name = ?",
                (book_id, field_name),
            )
        self._conn.commit()

    def get_locked_fields(self, book_id: int) -> set[str]:
        """Return the set of field names currently locked on this book."""
        rows = self._conn.execute(
            "SELECT field_name FROM book_field_provenance "
            "WHERE book_id = ? AND locked = 1",
            (book_id,),
        ).fetchall()
        return {row["field_name"] for row in rows}

    def get_provenance(self, book_id: int) -> dict[str, ProvenanceEntry]:
        """Return all provenance rows for a book, keyed by field name."""
        rows = self._conn.execute(
            "SELECT field_name, source, fetched_at, confidence, locked "
            "FROM book_field_provenance WHERE book_id = ? ORDER BY field_name",
            (book_id,),
        ).fetchall()
        return {
            row["field_name"]: ProvenanceEntry(
                field_name=row["field_name"],
                source=row["source"],
                fetched_at=row["fetched_at"],
                confidence=row["confidence"],
                locked=bool(row["locked"]),
            )
            for row in rows
        }

    def set_output_path(self, book_id: int, output_path: Path) -> None:
        """Set the output_path for a cataloged book."""
        self.update_book(book_id, output_path=str(output_path))

    def delete_book(self, book_id: int) -> None:
        """Delete a book from the catalog.

        Raises:
            ValueError: If the book_id does not exist.
        """
        cursor = self._conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        self._conn.commit()

        if cursor.rowcount == 0:
            raise ValueError(f"Book with id {book_id} not found")

    # --- Tag operations ---

    def add_tag(self, book_id: int, tag_name: str) -> None:
        """Tag a book. Creates the tag if it doesn't exist. Idempotent.

        Raises:
            ValueError: If the book_id does not exist.
        """
        if self.get_by_id(book_id) is None:
            raise ValueError(f"Book with id {book_id} not found")

        self._conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
        self._conn.execute(
            "INSERT OR IGNORE INTO book_tags (book_id, tag_id) "
            "SELECT ?, id FROM tags WHERE name = ?",
            (book_id, tag_name),
        )
        self._conn.commit()

    def remove_tag(self, book_id: int, tag_name: str) -> None:
        """Remove a tag from a book.

        Raises:
            ValueError: If the tag doesn't exist or the book isn't tagged with it.
        """
        cursor = self._conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,))
        tag_row = cursor.fetchone()
        if tag_row is None:
            raise ValueError(f"Tag '{tag_name}' not found")

        tag_id = tag_row[0]
        cursor = self._conn.execute(
            "DELETE FROM book_tags WHERE book_id = ? AND tag_id = ?",
            (book_id, tag_id),
        )
        self._conn.commit()

        if cursor.rowcount == 0:
            raise ValueError(f"Book {book_id} is not tagged with '{tag_name}'")

    def get_tags_for_book(self, book_id: int) -> list[str]:
        """Get all tags for a book, alphabetically sorted."""
        cursor = self._conn.execute(
            "SELECT t.name FROM tags t "
            "JOIN book_tags bt ON t.id = bt.tag_id "
            "WHERE bt.book_id = ? "
            "ORDER BY t.name",
            (book_id,),
        )
        return [row[0] for row in cursor.fetchall()]

    def list_tags(self) -> list[tuple[str, int]]:
        """List all tags with their book counts, alphabetically sorted."""
        cursor = self._conn.execute(
            "SELECT t.name, COUNT(bt.book_id) as book_count "
            "FROM tags t "
            "JOIN book_tags bt ON t.id = bt.tag_id "
            "GROUP BY t.id "
            "ORDER BY t.name"
        )
        return [(row[0], row[1]) for row in cursor.fetchall()]

    def get_books_by_tag(self, tag_name: str) -> list[BookRecord]:
        """Get all books with a given tag.

        Raises:
            ValueError: If the tag doesn't exist.
        """
        cursor = self._conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,))
        if cursor.fetchone() is None:
            raise ValueError(f"Tag '{tag_name}' not found")

        cursor = self._conn.execute(
            "SELECT b.* FROM books b "
            "JOIN book_tags bt ON b.id = bt.book_id "
            "JOIN tags t ON bt.tag_id = t.id "
            "WHERE t.name = ? "
            "ORDER BY b.title",
            (tag_name,),
        )
        return [row_to_record(row) for row in cursor.fetchall()]

    # --- Genre operations ---

    def add_genre(self, book_id: int, genre_name: str, *, is_primary: bool = False) -> None:
        """Assign a canonical genre to a book. Idempotent.

        Raises:
            ValueError: If the genre is not canonical or the book doesn't exist.
        """
        if not is_canonical_genre(genre_name):
            raise ValueError(f"'{genre_name}' is not a canonical genre")
        if self.get_by_id(book_id) is None:
            raise ValueError(f"Book with id {book_id} not found")

        cursor = self._conn.execute("SELECT id FROM genres WHERE name = ?", (genre_name,))
        genre_id = cursor.fetchone()[0]

        self._conn.execute(
            "INSERT OR IGNORE INTO book_genres (book_id, genre_id, is_primary) VALUES (?, ?, ?)",
            (book_id, genre_id, int(is_primary)),
        )
        self._conn.commit()

    def remove_genre(self, book_id: int, genre_name: str) -> None:
        """Remove a genre from a book.

        Raises:
            ValueError: If the genre is not assigned to the book.
        """
        cursor = self._conn.execute("SELECT id FROM genres WHERE name = ?", (genre_name,))
        genre_row = cursor.fetchone()
        if genre_row is None:
            raise ValueError(f"Genre '{genre_name}' not assigned to book {book_id}")

        genre_id = genre_row[0]
        cursor = self._conn.execute(
            "DELETE FROM book_genres WHERE book_id = ? AND genre_id = ?",
            (book_id, genre_id),
        )
        self._conn.commit()

        if cursor.rowcount == 0:
            raise ValueError(f"Genre '{genre_name}' not assigned to book {book_id}")

    def set_primary_genre(self, book_id: int, genre_name: str) -> None:
        """Set a genre as the primary for a book, clearing any previous primary.

        The genre must already be assigned to the book.
        """
        # Clear existing primary
        self._conn.execute(
            "UPDATE book_genres SET is_primary = 0 WHERE book_id = ?",
            (book_id,),
        )
        # Set new primary
        cursor = self._conn.execute("SELECT id FROM genres WHERE name = ?", (genre_name,))
        genre_id = cursor.fetchone()[0]
        self._conn.execute(
            "UPDATE book_genres SET is_primary = 1 WHERE book_id = ? AND genre_id = ?",
            (book_id, genre_id),
        )
        self._conn.commit()

    def get_genres_for_book(self, book_id: int) -> list[tuple[str, bool]]:
        """Get all genres for a book as (name, is_primary) pairs, sorted by name."""
        cursor = self._conn.execute(
            "SELECT g.name, bg.is_primary FROM genres g "
            "JOIN book_genres bg ON g.id = bg.genre_id "
            "WHERE bg.book_id = ? "
            "ORDER BY g.name",
            (book_id,),
        )
        return [(row[0], bool(row[1])) for row in cursor.fetchall()]

    def get_primary_genre(self, book_id: int) -> str | None:
        """Get the primary genre name for a book, or None."""
        cursor = self._conn.execute(
            "SELECT g.name FROM genres g "
            "JOIN book_genres bg ON g.id = bg.genre_id "
            "WHERE bg.book_id = ? AND bg.is_primary = 1",
            (book_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def list_genres(self) -> list[tuple[str, int]]:
        """List all canonical genres with their book counts, sorted by name."""
        cursor = self._conn.execute(
            "SELECT g.name, COUNT(bg.book_id) as book_count "
            "FROM genres g "
            "LEFT JOIN book_genres bg ON g.id = bg.genre_id "
            "GROUP BY g.id "
            "ORDER BY g.name"
        )
        return [(row[0], row[1]) for row in cursor.fetchall()]

    def get_books_by_genre(self, genre_name: str) -> list[BookRecord]:
        """Get all books with a given genre.

        Raises:
            ValueError: If the genre is not a canonical genre.
        """
        if not is_canonical_genre(genre_name):
            raise ValueError(f"'{genre_name}' is not a canonical genre")

        cursor = self._conn.execute(
            "SELECT b.* FROM books b "
            "JOIN book_genres bg ON b.id = bg.book_id "
            "JOIN genres g ON bg.genre_id = g.id "
            "WHERE g.name = ? "
            "ORDER BY b.title",
            (genre_name,),
        )
        return [row_to_record(row) for row in cursor.fetchall()]

    def store_subjects(self, book_id: int, subjects: list[str]) -> None:
        """Update the subjects JSON column for a book."""
        self.update_book(book_id, subjects=subjects)

    def get_books_with_subjects(self) -> list[tuple[int, str, list[str]]]:
        """Get all books that have subjects, regardless of genre status.

        Returns list of (book_id, title, subjects) tuples.
        """
        cursor = self._conn.execute(
            "SELECT b.id, b.title, b.subjects FROM books b "
            "WHERE b.subjects IS NOT NULL AND b.subjects != '[]' "
            "ORDER BY b.title"
        )
        results: list[tuple[int, str, list[str]]] = []
        for row in cursor.fetchall():
            subjects = json.loads(row[2]) if row[2] else []
            results.append((row[0], row[1], subjects))
        return results

    def get_unmatched_subjects(self) -> list[tuple[int, str, list[str]]]:
        """Get books that have subjects but no genre assigned.

        Returns list of (book_id, title, subjects) tuples.
        """
        cursor = self._conn.execute(
            "SELECT b.id, b.title, b.subjects FROM books b "
            "WHERE b.subjects IS NOT NULL AND b.subjects != '[]' "
            "AND b.id NOT IN (SELECT book_id FROM book_genres) "
            "ORDER BY b.title"
        )
        results: list[tuple[int, str, list[str]]] = []
        for row in cursor.fetchall():
            subjects = json.loads(row[2]) if row[2] else []
            results.append((row[0], row[1], subjects))
        return results

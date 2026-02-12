# ABOUTME: CRUD operations for the Bookery library catalog.
# ABOUTME: Add, query, update, and delete books in the SQLite database.

import json
import sqlite3
from pathlib import Path

from bookery.db.mapping import BookRecord, metadata_to_row, row_to_record
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
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed: books.file_hash" in str(exc):
                raise DuplicateBookError(
                    f"Book with hash {file_hash} already exists"
                ) from exc
            raise

        return cursor.lastrowid  # type: ignore[return-value]

    def get_by_id(self, book_id: int) -> BookRecord | None:
        """Retrieve a book by its row ID."""
        cursor = self._conn.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        return row_to_record(row) if row else None

    def get_by_hash(self, file_hash: str) -> BookRecord | None:
        """Retrieve a book by its file hash."""
        cursor = self._conn.execute(
            "SELECT * FROM books WHERE file_hash = ?", (file_hash,)
        )
        row = cursor.fetchone()
        return row_to_record(row) if row else None

    def get_by_isbn(self, isbn: str) -> BookRecord | None:
        """Retrieve a book by its ISBN."""
        cursor = self._conn.execute(
            "SELECT * FROM books WHERE isbn = ?", (isbn,)
        )
        row = cursor.fetchone()
        return row_to_record(row) if row else None

    def list_all(self) -> list[BookRecord]:
        """Return all books in the catalog, ordered by title."""
        cursor = self._conn.execute("SELECT * FROM books ORDER BY title")
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

    def update_book(self, book_id: int, **fields: str | list[str] | float | None) -> None:
        """Update one or more fields on a cataloged book.

        Accepts keyword arguments matching books table columns. Authors and
        identifiers values are JSON-serialized automatically.

        Raises:
            ValueError: If the book_id does not exist.
        """
        if not fields:
            return

        # JSON-serialize list/dict fields
        if "authors" in fields:
            fields["authors"] = json.dumps(fields["authors"])
        if "identifiers" in fields:
            fields["identifiers"] = json.dumps(fields["identifiers"])

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        set_clause += ", date_modified = strftime('%Y-%m-%dT%H:%M:%S', 'now')"
        values = [*list(fields.values()), book_id]

        cursor = self._conn.execute(
            f"UPDATE books SET {set_clause} WHERE id = ?",
            values,
        )
        self._conn.commit()

        if cursor.rowcount == 0:
            raise ValueError(f"Book with id {book_id} not found")

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

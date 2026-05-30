# ABOUTME: CRUD operations for the Bookery library catalog.
# ABOUTME: Add, query, update, and delete books in the SQLite database.

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

from bookery.collections import (
    Op,
    QueryAnd,
    QueryNode,
    QueryNot,
    QueryOr,
    QueryTerm,
    parse_collection_query,
)
from bookery.core.dedup import (
    normalize_author_for_dedup,
    normalize_for_dedup,
    normalize_isbn,
)
from bookery.core.text_sort import compute_author_sort, compute_title_sort
from bookery.db.mapping import (
    BookRecord,
    DuplicateMatch,
    ProvenanceEntry,
    metadata_to_row,
    row_to_record,
)
from bookery.db.status import BookStatus, DeviceReadState, PushCandidate
from bookery.metadata.genres import is_canonical_genre
from bookery.metadata.types import BookMetadata


class DuplicateBookError(Exception):
    """Raised when attempting to add a book with a file_hash that already exists."""


def _fts_match_expression(q: str) -> str:
    """Build a safe FTS5 MATCH expression from raw user input.

    FTS5 reserves characters like ``:`` (column filter), ``"`` (phrase),
    ``*`` (prefix), ``()`` (grouping), and bare words ``AND``/``OR``/``NOT``/
    ``NEAR`` as operators. Passing raw user input through directly will
    raise ``sqlite3.OperationalError`` when those tokens appear (e.g.
    ``dune:`` is read as a column filter against a non-existent column).

    The fix is to wrap each whitespace-separated token as an FTS5 phrase
    (``"token"``) with internal double-quotes doubled to escape them.
    Multiple phrases combine via FTS5's implicit AND, so ``rose garden``
    still requires both tokens.
    """
    tokens = q.split()
    if not tokens:
        return ""
    return " ".join('"' + tok.replace('"', '""') + '"' for tok in tokens)


# Map URL-layer sort keys to the column expressions used in ORDER BY clauses.
# ``added`` resolves to ``date_added`` (the schema column), with a stable
# tiebreaker on ``id`` so equal timestamps still produce a deterministic order.
# ``title`` and ``author`` use ``title_sort`` (article-stripped, populated on
# insert/update) so "The Hobbit" files under H rather than T — see #192.
_SORT_COLUMNS: dict[str, str] = {
    "title": "title_sort COLLATE NOCASE",
    "author": "author_sort COLLATE NOCASE, title_sort COLLATE NOCASE",
    "added": "date_added, id",
}
_DEFAULT_ORDER = "author_sort COLLATE NOCASE, title_sort COLLATE NOCASE"


def _order_clause_for(sort: str, dir: str) -> str:
    """Build an ORDER BY fragment for the browse query.

    Whitelist-driven — the inputs come from the trusted ``BrowseQuery`` layer
    but the catalog re-validates because it's the actual SQL boundary. Unknown
    keys fall back to the historical default ordering. The direction is
    appended to every key in the column expression so multi-key sorts flip
    together.
    """
    columns = _SORT_COLUMNS.get(sort)
    direction = "DESC" if dir == "desc" else "ASC"
    if columns is None:
        return _DEFAULT_ORDER
    # Apply the direction to each comma-separated key so secondary sort
    # tiebreakers respect the user's chosen direction.
    parts = [part.strip() for part in columns.split(",")]
    return ", ".join(f"{part} {direction}" for part in parts)


# Per-field SQL for a single query term. Every leaf compiles to a
# ``SELECT id FROM books b WHERE <predicate>`` returning a book-id set, with the
# value bound as a parameter (never interpolated). Many-to-many fields (genre,
# tag) use EXISTS so the outer shape stays uniform — later sub-slices compose
# these sets with INTERSECT/UNION/EXCEPT for boolean queries.
#
# ``author``/``subject`` are stored as JSON-array TEXT columns (e.g.
# ``["J.R.R. Tolkien"]``); contains-match runs LIKE against that JSON text, so a
# substring like ``Tolkien`` matches regardless of the array wrapping.


def _escape_like(value: str) -> str:
    """Escape LIKE metacharacters so user input matches literally (with ESCAPE '\\')."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _comparable_predicate(
    operand: str, term: QueryTerm, cast: Callable[[str], object]
) -> tuple[str, list[object]]:
    """Build a WHERE predicate for an ordered (numeric/date) operand.

    ``operand`` is a trusted SQL column/expression (never user input); user values
    flow only through bound ``?`` parameters, cast to the field's type. Handles
    EQ/GE/GT/LE/LT and RANGE (open bounds skip their clause).
    """
    op = term.op
    if op is Op.EQ:
        return f"{operand} = ?", [cast(term.value)]  # type: ignore[arg-type]
    if op is Op.GE:
        return f"{operand} >= ?", [cast(term.value)]  # type: ignore[arg-type]
    if op is Op.GT:
        return f"{operand} > ?", [cast(term.value)]  # type: ignore[arg-type]
    if op is Op.LE:
        return f"{operand} <= ?", [cast(term.value)]  # type: ignore[arg-type]
    if op is Op.LT:
        return f"{operand} < ?", [cast(term.value)]  # type: ignore[arg-type]
    # Op.RANGE — one clause per present bound; an all-open range matches any non-null.
    clauses: list[str] = []
    params: list[object] = []
    if term.low is not None:
        clauses.append(f"{operand} {'>=' if term.include_low else '>'} ?")
        params.append(cast(term.low))
    if term.high is not None:
        clauses.append(f"{operand} {'<=' if term.include_high else '<'} ?")
        params.append(cast(term.high))
    if not clauses:
        return f"{operand} IS NOT NULL", []
    return " AND ".join(clauses), params


def _compile_node(node: QueryNode) -> tuple[str, list[object]]:
    """Compile a query IR node to ``(sql, params)`` yielding a book-id set.

    Booleans compose via ``b.id IN (subquery)`` / ``NOT IN`` rather than raw
    compound set operators: SQLite won't parenthesise compound SELECTs, but nested
    ``IN`` subqueries give clean, precedence-safe composition with full parameter
    binding. AND joins child membership with ``AND``, OR with ``OR``, NOT negates.
    """
    if isinstance(node, QueryTerm):
        return _compile_term(node)
    if isinstance(node, QueryAnd):
        return _compile_boolean(node.children, "AND")
    if isinstance(node, QueryOr):
        return _compile_boolean(node.children, "OR")
    if isinstance(node, QueryNot):
        sql, params = _compile_node(node.child)
        return f"SELECT id FROM books b WHERE b.id NOT IN ({sql})", params
    # Exhaustive over QueryNode; unreachable for validated trees.
    raise ValueError(f"Unsupported query node: {type(node).__name__}")  # pragma: no cover


def _compile_boolean(
    children: tuple[QueryNode, ...], conjunction: str
) -> tuple[str, list[object]]:
    """Combine child node membership with AND/OR via nested ``b.id IN (...)`` clauses."""
    clauses: list[str] = []
    params: list[object] = []
    for child in children:
        sql, child_params = _compile_node(child)
        clauses.append(f"b.id IN ({sql})")
        params.extend(child_params)
    joined = f" {conjunction} ".join(clauses)
    return f"SELECT id FROM books b WHERE {joined}", params


def _compile_term(term: QueryTerm) -> tuple[str, list[object]]:
    """Compile one validated ``QueryTerm`` to ``(sql, params)`` yielding a book-id set."""
    field, op, value = term.field, term.op, term.value

    if field == "year":
        # The 4-char year prefix of the (ISO) edition date, compared numerically.
        pred, params = _comparable_predicate(
            "CAST(substr(b.published_date, 1, 4) AS INTEGER)", term, int
        )
        return f"SELECT id FROM books b WHERE {pred}", params
    if field == "rating":
        pred, params = _comparable_predicate("b.rating", term, float)
        return f"SELECT id FROM books b WHERE {pred}", params
    if field == "added":
        # Compare the date portion of the stored ISO timestamp (day granularity).
        pred, params = _comparable_predicate("substr(b.date_added, 1, 10)", term, str)
        return f"SELECT id FROM books b WHERE {pred}", params

    # Remaining fields are scalar-only; the validator guarantees a non-null value.
    assert value is not None
    if field == "id":
        return ("SELECT id FROM books b WHERE b.id = ?", [int(value)])
    if field == "isbn":
        return ("SELECT id FROM books b WHERE b.isbn = ?", [value])
    if field == "language":
        return ("SELECT id FROM books b WHERE b.language = ? COLLATE NOCASE", [value])
    if field == "publisher":
        return ("SELECT id FROM books b WHERE b.publisher = ? COLLATE NOCASE", [value])
    if field == "series":
        return ("SELECT id FROM books b WHERE b.series = ? COLLATE NOCASE", [value])
    if field == "title":
        if op is Op.PREFIX:
            return (
                "SELECT id FROM books b WHERE b.title LIKE ? ESCAPE '\\' COLLATE NOCASE",
                [f"{_escape_like(value)}%"],
            )
        return ("SELECT id FROM books b WHERE b.title = ? COLLATE NOCASE", [value])
    if field == "author":
        return (
            "SELECT id FROM books b WHERE b.authors LIKE ? ESCAPE '\\' COLLATE NOCASE",
            [f"%{_escape_like(value)}%"],
        )
    if field == "subject":
        return (
            "SELECT id FROM books b WHERE b.subjects LIKE ? ESCAPE '\\' COLLATE NOCASE",
            [f"%{_escape_like(value)}%"],
        )
    if field == "genre":
        return (
            "SELECT id FROM books b WHERE EXISTS ("
            "SELECT 1 FROM book_genres bg JOIN genres g ON bg.genre_id = g.id "
            "WHERE bg.book_id = b.id AND g.name = ?)",
            [value],
        )
    if field == "tag":
        return (
            "SELECT id FROM books b WHERE EXISTS ("
            "SELECT 1 FROM book_tags bt JOIN tags t ON bt.tag_id = t.id "
            "WHERE bt.book_id = b.id AND t.name = ?)",
            [value],
        )
    # Guarded by the query validator; unreachable for whitelisted fields.
    raise ValueError(f"Unsupported query field: {field}")  # pragma: no cover


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
        """Return all books in the catalog, author-then-article-stripped-title.

        Mirrors the web default at ``/books`` so ``bookery ls`` and the web
        list ship the same order (#192). Same SQL as ``list_all_by_author``;
        kept as a separate method because most CLI callers historically used
        this name and changing the public surface would be churn for no gain.
        """
        cursor = self._conn.execute(
            "SELECT * FROM books ORDER BY author_sort COLLATE NOCASE, title_sort COLLATE NOCASE"
        )
        return [row_to_record(row) for row in cursor.fetchall()]

    def list_all_by_author(self) -> list[BookRecord]:
        """Return all books in the catalog, ordered by author then title.

        Secondary sort is on the article-stripped ``title_sort`` column so the
        order matches the web's default ``/books`` listing.
        """
        cursor = self._conn.execute(
            "SELECT * FROM books ORDER BY author_sort COLLATE NOCASE, title_sort COLLATE NOCASE"
        )
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
        match = _fts_match_expression(query)
        if not match:
            return []
        cursor = self._conn.execute(
            "SELECT books.* FROM books "
            "JOIN books_fts ON books.id = books_fts.rowid "
            "WHERE books_fts MATCH ? "
            "ORDER BY books_fts.rank",
            (match,),
        )
        return [row_to_record(row) for row in cursor.fetchall()]

    def browse(
        self,
        *,
        q: str = "",
        offset: int = 0,
        limit: int = 50,
        sort: str = "",
        dir: str = "",
        enriched: str | None = None,
        format: str | None = None,
        language: str | None = None,
        status: str | None = None,
    ) -> tuple[list[BookRecord], int]:
        """Paginated browse over the catalog.

        Empty ``q`` returns rows ordered by ``sort`` + ``dir`` (default:
        ``author_sort, title`` ascending). A non-empty ``q`` runs an FTS5
        MATCH ranked by relevance and ignores ``sort`` — relevance is the
        useful ordering for a search. ``offset`` and ``limit`` are applied
        server-side so the caller never sees rows beyond the requested page.
        The second tuple element is the total count for the query
        (independent of ``offset`` and ``limit``) so the controller can drive
        paging UI without a second round-trip.

        Filters (``enriched`` / ``format`` / ``language``) AND together and
        with ``q``. ``enriched`` accepts the strings ``"1"`` / ``"0"`` and
        maps to ``metadata_matched_at IS NOT NULL`` / ``IS NULL`` — the
        explicit "matched against a provider" signal landed in V7. ``format``
        is matched against the lowercase extension of ``source_path`` (the
        only path column guaranteed to be present per the schema NOT NULL
        constraint); ``output_path`` shares the same extension after a copy.
        ``language`` is an exact match on the ``language`` column. Unknown
        ``sort`` / ``dir`` values and unknown ``enriched`` values fall back
        silently — callers are expected to validate at the URL layer
        (``BrowseQuery``) but the catalog stays robust on its own. All
        filter values bind as parameters; nothing string-interpolates.
        """
        filter_sql, filter_params = self._filter_clauses(
            enriched=enriched, format=format, language=language, status=status
        )
        match = _fts_match_expression(q) if q else ""
        if match:
            where = "WHERE books_fts MATCH ?" + (
                " AND " + " AND ".join(filter_sql) if filter_sql else ""
            )
            params: list[object] = [match, *filter_params]
            total_row = self._conn.execute(
                f"SELECT COUNT(*) FROM books JOIN books_fts ON books.id = books_fts.rowid {where}",
                params,
            ).fetchone()
            total = int(total_row[0]) if total_row else 0
            cursor = self._conn.execute(
                f"SELECT books.* FROM books "
                f"JOIN books_fts ON books.id = books_fts.rowid {where} "
                f"ORDER BY books_fts.rank "
                f"LIMIT ? OFFSET ?",
                [*params, limit, offset],
            )
        else:
            where = ("WHERE " + " AND ".join(filter_sql)) if filter_sql else ""
            total_row = self._conn.execute(
                f"SELECT COUNT(*) FROM books {where}".strip(),
                filter_params,
            ).fetchone()
            total = int(total_row[0]) if total_row else 0
            order_clause = _order_clause_for(sort, dir)
            cursor = self._conn.execute(
                f"SELECT * FROM books {where} ORDER BY {order_clause} LIMIT ? OFFSET ?".strip(),
                [*filter_params, limit, offset],
            )
        records = [row_to_record(row) for row in cursor.fetchall()]
        return records, total

    @staticmethod
    def _filter_clauses(
        *,
        enriched: str | None,
        format: str | None,
        language: str | None,
        status: str | None = None,
    ) -> tuple[list[str], list[object]]:
        """Translate browse filter args into SQL fragments + bind values.

        Returns a list of WHERE-clause fragments (each fully parenthesized
        and AND-safe) plus the parameters they consume, in order. Unknown
        ``enriched`` values are dropped — defense in depth on top of the URL
        layer's ``ALLOWED_FILTERS`` whitelist. Format matching uses
        ``LOWER(source_path) LIKE '%.' || ?`` rather than SQLite's
        ``substr``/``instr`` so the extension comparison is case-insensitive
        without forcing the input to a particular case.

        ``status`` is expressed as an EXISTS / NOT EXISTS subquery against
        ``book_status`` rather than a join so the outer query's row
        structure stays identical to the unfiltered case (the FTS variant
        already joins on ``books_fts``; adding a second join would force
        a column-qualified rewrite). ``"unread"`` is "no row OR row with
        status=0" — captured as ``NOT EXISTS(... AND status > 0)``.
        """
        clauses: list[str] = []
        params: list[object] = []
        if enriched == "1":
            clauses.append("metadata_matched_at IS NOT NULL")
        elif enriched == "0":
            clauses.append("metadata_matched_at IS NULL")
        if format:
            clauses.append("LOWER(source_path) LIKE '%.' || ?")
            params.append(format.lower())
        if language:
            clauses.append("language = ?")
            params.append(language)
        if status == "reading":
            clauses.append(
                "EXISTS (SELECT 1 FROM book_status "
                "WHERE book_status.book_id = books.id AND book_status.status = 1)"
            )
        elif status == "finished":
            clauses.append(
                "EXISTS (SELECT 1 FROM book_status "
                "WHERE book_status.book_id = books.id AND book_status.status = 2)"
            )
        elif status == "unread":
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM book_status "
                "WHERE book_status.book_id = books.id AND book_status.status > 0)"
            )
        return clauses, params

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

        # Keep the persisted `title_sort` in lock-step with `title` so the
        # article-stripped sort key never drifts after a title edit. Compute
        # before JSON-serialization so the helper sees a plain string.
        if "title" in fields:
            title_val = fields["title"]
            fields["title_sort"] = (
                compute_title_sort(title_val) if isinstance(title_val, str) and title_val else None
            )

        # Author-side twin: when `authors` changes (and the caller didn't
        # explicitly set `author_sort` in the same call), re-derive the sort
        # key from the new list so it stays in lock-step. An explicit
        # `author_sort` always wins — curator/provider intent is respected.
        # Runs before JSON-serialization so the helper sees a plain list.
        if "authors" in fields and "author_sort" not in fields:
            authors_val = fields["authors"]
            if isinstance(authors_val, list):
                fields["author_sort"] = compute_author_sort(authors_val)

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
                    "DELETE FROM book_field_provenance WHERE book_id = ? AND field_name = ?",
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
                "UPDATE book_field_provenance SET locked = 0 WHERE book_id = ? AND field_name = ?",
                (book_id, field_name),
            )
        self._conn.commit()

    def get_locked_fields(self, book_id: int) -> set[str]:
        """Return the set of field names currently locked on this book."""
        rows = self._conn.execute(
            "SELECT field_name FROM book_field_provenance WHERE book_id = ? AND locked = 1",
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

    def set_matched_at(self, book_id: int, timestamp: str | None = None) -> None:
        """Mark a book as matched against a metadata provider.

        Writes ``metadata_matched_at``; defaults to the current UTC ISO
        timestamp. This is the explicit "this book has been matched" signal,
        distinct from ``output_path`` (which only records the on-disk location).
        """
        if timestamp is None:
            cursor = self._conn.execute(
                "UPDATE books SET metadata_matched_at = "
                "strftime('%Y-%m-%dT%H:%M:%S', 'now') WHERE id = ?",
                (book_id,),
            )
        else:
            cursor = self._conn.execute(
                "UPDATE books SET metadata_matched_at = ? WHERE id = ?",
                (timestamp, book_id),
            )
        self._conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"Book with id {book_id} not found")

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
            "ORDER BY b.title_sort COLLATE NOCASE",
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
            "ORDER BY b.title_sort COLLATE NOCASE",
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

    # --- Device / read-status (SCHEMA_V8) -------------------------------

    def upsert_device(self, *, kind: str, serial: str, label: str | None, now: str) -> int:
        """Insert or refresh a device row; return its id.

        Devices are uniquely identified by (kind, serial). On re-sync we
        update `label` and `last_seen_at` but preserve the id so foreign keys
        in device_read_state and device_files stay stable.
        """
        self._conn.execute(
            """
            INSERT INTO devices (kind, serial, label, last_seen_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(kind, serial) DO UPDATE SET
                label = excluded.label,
                last_seen_at = excluded.last_seen_at
            """,
            (kind, serial, label, now),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM devices WHERE kind = ? AND serial = ?",
            (kind, serial),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def upsert_device_file(
        self, *, device_id: int, book_id: int, remote_path: str, now: str
    ) -> None:
        """Record the on-device path for a book copied during sync.

        Replaces `remote_path` on conflict so the resolver always points at
        the current file — if a book's destination changes (e.g. title edit
        propagates a new directory), the next sync overwrites cleanly.
        """
        self._conn.execute(
            """
            INSERT INTO device_files (device_id, book_id, remote_path, written_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(device_id, book_id) DO UPDATE SET
                remote_path = excluded.remote_path,
                written_at = excluded.written_at
            """,
            (device_id, book_id, remote_path, now),
        )
        self._conn.commit()

    def resolve_book_id_for_remote_path(self, *, device_id: int, remote_path: str) -> int | None:
        """Look up the catalog book id we wrote to `remote_path` on this device."""
        row = self._conn.execute(
            "SELECT book_id FROM device_files WHERE device_id = ? AND remote_path = ?",
            (device_id, remote_path),
        ).fetchone()
        return int(row["book_id"]) if row is not None else None

    def list_devices(self) -> list[dict[str, object]]:
        """Return all registered devices ordered by last seen."""
        cursor = self._conn.execute(
            """
            SELECT id, kind, serial, label, last_seen_at
            FROM devices
            ORDER BY last_seen_at DESC
            """
        )
        return [
            {
                "id": int(row["id"]),
                "kind": str(row["kind"]),
                "serial": str(row["serial"]),
                "label": row["label"],
                "last_seen_at": str(row["last_seen_at"]),
            }
            for row in cursor.fetchall()
        ]

    def upsert_device_read_state(
        self,
        *,
        device_id: int,
        book_id: int,
        read_status: int,
        percent_read: float | None,
        last_read_at: str | None,
        last_chapter_id: str | None,
        status_updated_at: str,
        pulled_at: str,
    ) -> None:
        """Persist the device-side read state pulled from KoboReader.sqlite."""
        self._conn.execute(
            """
            INSERT INTO device_read_state (
                device_id, book_id, read_status, percent_read,
                last_read_at, last_chapter_id, status_updated_at, pulled_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id, book_id) DO UPDATE SET
                read_status = excluded.read_status,
                percent_read = excluded.percent_read,
                last_read_at = excluded.last_read_at,
                last_chapter_id = excluded.last_chapter_id,
                status_updated_at = excluded.status_updated_at,
                pulled_at = excluded.pulled_at
            """,
            (
                device_id,
                book_id,
                read_status,
                percent_read,
                last_read_at,
                last_chapter_id,
                status_updated_at,
                pulled_at,
            ),
        )
        self._conn.commit()

    def seed_book_status_if_absent(self, *, book_id: int, status: int, updated_at: str) -> None:
        """Insert book_status only if no row exists for this book.

        The pull seeds the catalog-side mirror from device state, but P1b lets
        users set status directly via `bookery mark finished/reading/unread`. Once the
        user has set a value, the pull must never clobber it — hence ON CONFLICT
        DO NOTHING. Later phases overwrite via a different method.
        """
        self._conn.execute(
            """
            INSERT INTO book_status (book_id, status, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(book_id) DO NOTHING
            """,
            (book_id, status, updated_at),
        )
        self._conn.commit()

    def merge_book_status_from_device(
        self,
        *,
        book_id: int,
        device_status: int,
        device_updated_at: str,
    ) -> None:
        """Merge a device-side status into ``book_status`` using last-writer-wins.

        Overwrites the catalog row iff the device timestamp is greater than
        or equal to the catalog's existing ``updated_at`` (or the catalog has
        no row yet). The ``>=`` tiebreak comes from the #178 sync model: when
        two timestamps match exactly we let the device win, which keeps the
        two sides consistent without an extra "are these really the same"
        check. This replaces ``seed_book_status_if_absent`` for P2 — the pull
        now respects user intent only when the catalog timestamp is strictly
        newer, not whenever the user happened to touch the book first.
        """
        existing = self._conn.execute(
            "SELECT updated_at FROM book_status WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        if existing is not None and str(existing["updated_at"]) > device_updated_at:
            return
        self._conn.execute(
            """
            INSERT INTO book_status (book_id, status, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(book_id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (book_id, device_status, device_updated_at),
        )
        self._conn.commit()

    def set_book_status(self, *, book_id: int, status: int, updated_at: str) -> None:
        """Upsert book_status for the user-write path.

        Differs from `seed_book_status_if_absent` in that this overwrites on
        conflict — the user's `bookery mark finished/reading/unread` command is the
        authoritative signal for catalog-side state. Raises ValueError if
        `book_id` is not in the books table so a bad CLI argument fails
        loudly instead of silently writing an orphan row that an FK
        constraint would later complain about anyway.
        """
        existing = self._conn.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone()
        if existing is None:
            raise ValueError(f"Book {book_id} not found.")
        self._conn.execute(
            """
            INSERT INTO book_status (book_id, status, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(book_id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (book_id, status, updated_at),
        )
        self._conn.commit()

    def set_book_statuses_bulk(
        self,
        *,
        book_ids: list[int],
        status: int,
        updated_at: str,
    ) -> list[int]:
        """Upsert ``book_status`` for many books in a single transaction.

        Powers the web bulk-mark action — "I just imported 200 books from
        Calibre, mark them all read". Differs from ``set_book_status``:

        - Unknown IDs are silently skipped (not raised). Bulk callers prefer
          a count over an exception when one stale ID is in the list.
        - Repeated IDs in the input are deduplicated so the caller doesn't
          have to scrub form-post values that may carry the same id twice.

        Returns the de-duplicated list of IDs that actually had a row
        written, preserving input order. An empty ``book_ids`` short-
        circuits without touching the DB.
        """
        if not book_ids:
            return []
        # Dedupe while preserving order — the first occurrence wins.
        seen: set[int] = set()
        unique_ids: list[int] = []
        for bid in book_ids:
            if bid not in seen:
                seen.add(bid)
                unique_ids.append(bid)
        # Filter to known book IDs before the write so we never insert an
        # orphan row that the FK constraint would later complain about. One
        # IN-clause query keeps this O(1) round trips.
        placeholders = ",".join("?" * len(unique_ids))
        cursor = self._conn.execute(
            f"SELECT id FROM books WHERE id IN ({placeholders})",
            unique_ids,
        )
        known_ids = {int(row["id"]) for row in cursor.fetchall()}
        writable = [bid for bid in unique_ids if bid in known_ids]
        if not writable:
            return []
        rows = [(bid, status, updated_at) for bid in writable]
        self._conn.executemany(
            """
            INSERT INTO book_status (book_id, status, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(book_id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            rows,
        )
        self._conn.commit()
        return writable

    def get_book_status(self, book_id: int) -> BookStatus | None:
        """Return the catalog-side read status for a book, or None if absent."""
        row = self._conn.execute(
            "SELECT book_id, status, updated_at FROM book_status WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        if row is None:
            return None
        return BookStatus(
            book_id=int(row["book_id"]),
            status=int(row["status"]),
            updated_at=str(row["updated_at"]),
        )

    def get_book_statuses(self, book_ids: list[int]) -> dict[int, BookStatus]:
        """Bulk lookup for the web list view: id → BookStatus.

        Books without a `book_status` row are silently omitted from the result;
        the template treats absence as "no chip". An empty ``book_ids`` short-
        circuits without hitting the DB so a paginated page with zero books
        skips the query entirely.
        """
        if not book_ids:
            return {}
        placeholders = ",".join("?" * len(book_ids))
        cursor = self._conn.execute(
            "SELECT book_id, status, updated_at FROM book_status "
            f"WHERE book_id IN ({placeholders})",
            book_ids,
        )
        return {
            int(row["book_id"]): BookStatus(
                book_id=int(row["book_id"]),
                status=int(row["status"]),
                updated_at=str(row["updated_at"]),
            )
            for row in cursor.fetchall()
        }

    def list_books_by_status(self, status: int) -> list[BookRecord]:
        """Return books with `book_status.status = ?`, ordered by article-stripped title."""
        cursor = self._conn.execute(
            """
            SELECT books.* FROM books
            JOIN book_status ON books.id = book_status.book_id
            WHERE book_status.status = ?
            ORDER BY books.title_sort COLLATE NOCASE
            """,
            (status,),
        )
        return [row_to_record(row) for row in cursor.fetchall()]

    def list_books_unread(self) -> list[BookRecord]:
        """Return books that are either unread or have no status row, by title.

        "Unread" in the bookery model is the union of two cases: a book that
        has never been touched (no `book_status` row), and a book the user has
        explicitly marked unread (`status = 0`). The CLI's `ls --unread`
        flattens both.
        """
        cursor = self._conn.execute(
            """
            SELECT books.* FROM books
            LEFT JOIN book_status ON books.id = book_status.book_id
            WHERE book_status.book_id IS NULL OR book_status.status = 0
            ORDER BY books.title_sort COLLATE NOCASE
            """,
        )
        return [row_to_record(row) for row in cursor.fetchall()]

    def is_status_queued_for_push(self, book_id: int) -> bool:
        """True when the catalog-side status is newer than the latest device.

        Powers the "Queued for next sync" indicator on the web detail page.
        Compares ``book_status.updated_at`` against the most recent
        ``device_read_state.status_updated_at`` across all devices:

        - No ``book_status`` row → nothing to push, returns False.
        - No ``device_read_state`` row → catalog has news that no device has
          seen, returns True.
        - Otherwise → strict `>` comparison (string-sorts ISO-8601 timestamps,
          which is the same ordering convention ``merge_book_status_from_device``
          uses for its tiebreak).
        """
        catalog_row = self._conn.execute(
            "SELECT updated_at FROM book_status WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        if catalog_row is None:
            return False
        catalog_ts = str(catalog_row["updated_at"])
        device_row = self._conn.execute(
            "SELECT MAX(status_updated_at) AS latest FROM device_read_state WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        if device_row is None or device_row["latest"] is None:
            return True
        return catalog_ts > str(device_row["latest"])

    def get_device_read_state_for_book(self, book_id: int) -> DeviceReadState | None:
        """Return the most-recent device read state for a book, joined with devices.

        When two devices both have a row for the same book (e.g. user paired
        and read on two Kobos), the row with the latest `status_updated_at`
        wins — that's what the user is actively touching. Returns None when no
        device has ever pulled a state for this book.
        """
        row = self._conn.execute(
            """
            SELECT
                drs.device_id,
                drs.book_id,
                drs.read_status,
                drs.percent_read,
                drs.last_read_at,
                drs.status_updated_at,
                devices.kind AS device_kind,
                devices.label AS device_label
            FROM device_read_state AS drs
            JOIN devices ON devices.id = drs.device_id
            WHERE drs.book_id = ?
            ORDER BY drs.status_updated_at DESC
            LIMIT 1
            """,
            (book_id,),
        ).fetchone()
        if row is None:
            return None
        return DeviceReadState(
            device_id=int(row["device_id"]),
            device_kind=str(row["device_kind"]),
            device_label=row["device_label"],
            book_id=int(row["book_id"]),
            read_status=int(row["read_status"]),
            percent_read=float(row["percent_read"]) if row["percent_read"] is not None else None,
            last_read_at=row["last_read_at"],
            status_updated_at=str(row["status_updated_at"]),
        )

    def list_push_candidates(self, *, device_id: int) -> list[PushCandidate]:
        """Return rows the sync orchestrator can consider for a device push.

        A candidate has both a catalog ``book_status`` row (so we know what
        the user wants) and a ``device_files`` row for this device (so we
        know which ContentID to write to). ``device_read_state`` is a LEFT
        JOIN — books the device has never reported a read for still show
        up with ``device_status_updated_at = None`` so the orchestrator can
        push the catalog's intent unconditionally.
        """
        cursor = self._conn.execute(
            """
            SELECT
                df.book_id,
                df.remote_path,
                bs.status AS catalog_status,
                bs.updated_at AS catalog_updated_at,
                drs.status_updated_at AS device_status_updated_at
            FROM device_files AS df
            JOIN book_status AS bs ON bs.book_id = df.book_id
            LEFT JOIN device_read_state AS drs
                ON drs.book_id = df.book_id AND drs.device_id = df.device_id
            WHERE df.device_id = ?
            ORDER BY df.book_id
            """,
            (device_id,),
        )
        return [
            PushCandidate(
                book_id=int(row["book_id"]),
                remote_path=str(row["remote_path"]),
                catalog_status=int(row["catalog_status"]),
                catalog_updated_at=str(row["catalog_updated_at"]),
                device_status_updated_at=(
                    str(row["device_status_updated_at"])
                    if row["device_status_updated_at"] is not None
                    else None
                ),
            )
            for row in cursor.fetchall()
        ]

    # --- Collection operations (SCHEMA_V11) ----------------------------

    def create_collection(
        self, name: str, description: str | None = None, query: str | None = None
    ) -> int:
        """Create a new collection.

        Args:
            name: The collection name (unique, case-insensitive).
            description: Optional description of the collection.
            query: Optional rule query. When non-None the collection is
                rule-based (membership derived live from the query); when None
                it is static (explicit membership via ``collection_books``). The
                two kinds are mutually exclusive.

        Returns:
            The row ID of the inserted collection.

        Raises:
            sqlite3.IntegrityError: If a collection with this name already exists.
        """
        cursor = self._conn.execute(
            "INSERT INTO collections (name, description, query) VALUES (?, ?, ?)",
            (name, description, query),
        )
        self._conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def get_collection_by_id(self, collection_id: int) -> dict[str, object] | None:
        """Retrieve a collection by its ID.

        Returns:
            Dict with collection fields (including ``query``), or None if not found.
            ``query`` is None for static collections, the rule string otherwise.
        """
        row = self._conn.execute(
            "SELECT id, name, description, query, created_at, updated_at "
            "FROM collections WHERE id = ?",
            (collection_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "query": row["query"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_collection_by_name(self, name: str) -> dict[str, object] | None:
        """Retrieve a collection by its name (case-insensitive).

        Returns:
            Dict with collection fields (including ``query``), or None if not found.
        """
        row = self._conn.execute(
            "SELECT id, name, description, query, created_at, updated_at "
            "FROM collections WHERE name = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "query": row["query"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def add_books_to_collection(self, collection_id: int, book_ids: list[int]) -> None:
        """Add books to a collection.

        Args:
            collection_id: The ID of the collection.
            book_ids: List of book IDs to add.

        Raises:
            ValueError: If the collection or any book doesn't exist.
        """
        # Verify collection exists
        if self.get_collection_by_id(collection_id) is None:
            raise ValueError(f"Collection {collection_id} not found")

        if not book_ids:
            return

        # Verify all books exist
        placeholders = ",".join("?" * len(book_ids))
        cursor = self._conn.execute(
            f"SELECT id FROM books WHERE id IN ({placeholders})",
            book_ids,
        )
        existing_ids = {int(row["id"]) for row in cursor.fetchall()}
        missing_ids = set(book_ids) - existing_ids
        if missing_ids:
            raise ValueError(f"Books not found: {sorted(missing_ids)}")

        # Insert into junction table (ignore duplicates)
        rows = [(collection_id, book_id) for book_id in book_ids]
        self._conn.executemany(
            "INSERT OR IGNORE INTO collection_books (collection_id, book_id) VALUES (?, ?)",
            rows,
        )
        self._conn.commit()

    def remove_books_from_collection(self, collection_id: int, book_ids: list[int]) -> None:
        """Remove books from a collection.

        Args:
            collection_id: The ID of the collection.
            book_ids: List of book IDs to remove.

        Raises:
            ValueError: If the collection doesn't exist.
        """
        # Verify collection exists
        if self.get_collection_by_id(collection_id) is None:
            raise ValueError(f"Collection {collection_id} not found")

        if not book_ids:
            return

        # Delete from junction table
        placeholders = ",".join("?" * len(book_ids))
        self._conn.execute(
            f"DELETE FROM collection_books WHERE collection_id = ? "
            f"AND book_id IN ({placeholders})",
            [collection_id, *book_ids],
        )
        self._conn.commit()

    def list_collections(self) -> list[dict[str, object]]:
        """List all collections with their (live) book counts.

        Returns:
            List of dicts with collection fields plus 'book_count'. For static
            collections the count is the number of ``collection_books`` rows; for
            rule-based collections (``query`` set) it is the live-resolved member
            count, since those hold no ``collection_books`` rows.
        """
        cursor = self._conn.execute(
            """
            SELECT c.id, c.name, c.description, c.query, c.created_at, c.updated_at,
                   COUNT(cb.book_id) AS book_count
            FROM collections c
            LEFT JOIN collection_books cb ON c.id = cb.collection_id
            GROUP BY c.id
            ORDER BY c.name COLLATE NOCASE
            """
        )
        collections: list[dict[str, object]] = []
        for row in cursor.fetchall():
            query = row["query"]
            # Rule-based collections keep zero collection_books rows, so the JOIN
            # count is always 0 — resolve their membership live instead.
            book_count = (
                len(self.resolve_collection_member_ids(int(row["id"])))
                if query is not None
                else row["book_count"]
            )
            collections.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "query": query,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "book_count": book_count,
                }
            )
        return collections

    def get_collection_books(self, collection_id: int) -> list[BookRecord]:
        """Get all books in a collection, ordered by title_sort.

        Works for both kinds: static collections read ``collection_books``,
        rule-based collections resolve their membership live from the query. This
        is a thin alias for :meth:`resolve_collection_members`, kept for existing
        callers (web detail, CLI ``show``).

        Args:
            collection_id: The ID of the collection.

        Returns:
            List of BookRecords in the collection.

        Raises:
            ValueError: If the collection doesn't exist.
        """
        return self.resolve_collection_members(collection_id)

    # --- Rule-based collection resolution (SCHEMA_V14, issue #240) -----

    def resolve_collection_member_ids(self, collection_id: int) -> list[int]:
        """Return the book IDs that belong to a collection.

        The sole membership entry point for both kinds. Static collections
        (``query IS NULL``) read explicit ``collection_books`` rows; rule-based
        collections (``query`` set) derive membership live by parsing and
        compiling the query. No caching — rule-based membership is recomputed on
        each call so it is never stale.

        Raises:
            ValueError: If the collection doesn't exist.
            CollectionQueryError: If a stored rule query is invalid.
        """
        collection = self.get_collection_by_id(collection_id)
        if collection is None:
            raise ValueError(f"Collection {collection_id} not found")

        query = collection["query"]
        if query is None:
            cursor = self._conn.execute(
                "SELECT book_id FROM collection_books WHERE collection_id = ?",
                (collection_id,),
            )
            return [int(row["book_id"]) for row in cursor.fetchall()]

        compiled = parse_collection_query(str(query))
        return self._compile_query_member_ids(compiled)

    def resolve_collection_members(self, collection_id: int) -> list[BookRecord]:
        """Return the books in a collection as records, ordered by title_sort.

        Raises:
            ValueError: If the collection doesn't exist.
            CollectionQueryError: If a stored rule query is invalid.
        """
        member_ids = self.resolve_collection_member_ids(collection_id)
        return self._fetch_books_ordered(member_ids)

    def preview_query(self, query: str) -> list[BookRecord]:
        """Resolve a one-shot rule query to its matching books without saving.

        Raises:
            CollectionQueryError: If the query is invalid or unsupported.
        """
        compiled = parse_collection_query(query)
        member_ids = self._compile_query_member_ids(compiled)
        return self._fetch_books_ordered(member_ids)

    def resolve_query_preview(
        self, query: str, limit: int
    ) -> tuple[int, list[BookRecord]]:
        """Resolve an ad-hoc query WITHOUT persisting; return (total, sample).

        Reuses the stored-query engine path (parse + compile to parameterized
        SQL) so preview matching can never diverge from saved-collection
        matching. ``total`` is the full match count; ``sample`` is the first
        ``limit`` matches ordered by title_sort.

        Raises:
            CollectionQueryError: If the query is invalid or unsupported.
        """
        compiled = parse_collection_query(query)
        member_ids = self._compile_query_member_ids(compiled)
        total = len(member_ids)
        sample = self._fetch_books_ordered(member_ids, limit=limit)
        return total, sample

    def set_collection_query(self, collection_id: int, query: str) -> None:
        """Convert a collection to rule-based with the given query.

        Validates the query first (so an invalid query never mutates state), then
        drops any existing ``collection_books`` rows — a rule-based collection is
        mutually exclusive with static membership and holds none.

        Raises:
            ValueError: If the collection doesn't exist.
            CollectionQueryError: If the query is invalid or unsupported.
        """
        parse_collection_query(query)  # validate before any write
        if self.get_collection_by_id(collection_id) is None:
            raise ValueError(f"Collection {collection_id} not found")

        self._conn.execute(
            "DELETE FROM collection_books WHERE collection_id = ?",
            (collection_id,),
        )
        self._conn.execute(
            "UPDATE collections SET query = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now') WHERE id = ?",
            (query, collection_id),
        )
        self._conn.commit()

    def clear_collection_query(self, collection_id: int) -> None:
        """Convert a rule-based collection to static, snapshotting current members.

        The live-resolved members are written into ``collection_books`` before the
        query is cleared, so the collection keeps exactly the books it matched at
        conversion time.

        Raises:
            ValueError: If the collection doesn't exist.
        """
        collection = self.get_collection_by_id(collection_id)
        if collection is None:
            raise ValueError(f"Collection {collection_id} not found")

        # Resolve while still rule-based, then snapshot before clearing the query.
        member_ids = self.resolve_collection_member_ids(collection_id)
        self._conn.executemany(
            "INSERT OR IGNORE INTO collection_books (collection_id, book_id) VALUES (?, ?)",
            [(collection_id, book_id) for book_id in member_ids],
        )
        self._conn.execute(
            "UPDATE collections SET query = NULL, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now') WHERE id = ?",
            (collection_id,),
        )
        self._conn.commit()

    def _compile_query_member_ids(self, query: QueryNode) -> list[int]:
        """Compile a validated query tree into the matching book IDs.

        The query module guarantees every leaf field is whitelisted and its value
        passed per-field validation. This only assembles parameter-bound SQL — user
        input is never interpolated into the statement text.
        """
        sql, params = _compile_node(query)
        cursor = self._conn.execute(sql, params)
        return [int(row[0]) for row in cursor.fetchall()]

    def _fetch_books_ordered(
        self, book_ids: list[int], *, limit: int | None = None
    ) -> list[BookRecord]:
        """Fetch the given books as records, ordered by title_sort.

        When ``limit`` is set, only the first ``limit`` records (after ordering)
        are returned — the cap is applied in SQL so a broad match never
        materializes every record.
        """
        if not book_ids:
            return []
        placeholders = ",".join("?" * len(book_ids))
        sql = (
            f"SELECT * FROM books WHERE id IN ({placeholders}) "
            "ORDER BY title_sort COLLATE NOCASE"
        )
        params: list[object] = list(book_ids)
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cursor = self._conn.execute(sql, params)
        return [row_to_record(row) for row in cursor.fetchall()]

    def delete_collection(self, collection_id: int) -> None:
        """Delete a collection and all its book associations.

        Args:
            collection_id: The ID of the collection to delete.

        Raises:
            ValueError: If the collection doesn't exist.
        """
        cursor = self._conn.execute(
            "DELETE FROM collections WHERE id = ?",
            (collection_id,),
        )
        self._conn.commit()

        if cursor.rowcount == 0:
            raise ValueError(f"Collection {collection_id} not found")

    def rename_collection(self, collection_id: int, new_name: str) -> None:
        """Rename a collection.

        Args:
            collection_id: The ID of the collection to rename.
            new_name: The new name for the collection.

        Raises:
            ValueError: If the collection doesn't exist.
            sqlite3.IntegrityError: If a collection with the new name already exists.
        """
        cursor = self._conn.execute(
            "UPDATE collections SET name = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now') WHERE id = ?",
            (new_name, collection_id),
        )
        self._conn.commit()

        if cursor.rowcount == 0:
            raise ValueError(f"Collection {collection_id} not found")

    def set_collection_description(
        self, collection_id: int, description: str | None
    ) -> None:
        """Set (or clear) a collection's description.

        Args:
            collection_id: The ID of the collection to update.
            description: The new description, or None to clear it.

        Raises:
            ValueError: If the collection doesn't exist.
        """
        cursor = self._conn.execute(
            "UPDATE collections SET description = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now') WHERE id = ?",
            (description, collection_id),
        )
        self._conn.commit()

        if cursor.rowcount == 0:
            raise ValueError(f"Collection {collection_id} not found")

    def get_collections_for_book(self, book_id: int) -> list[dict[str, object]]:
        """Get all collections that a book belongs to.

        Args:
            book_id: The ID of the book.

        Returns:
            List of collection dicts the book is in, ordered by collection name.
        """
        cursor = self._conn.execute(
            """
            SELECT c.id, c.name, c.description, c.created_at, c.updated_at
            FROM collections c
            JOIN collection_books cb ON c.id = cb.collection_id
            WHERE cb.book_id = ?
            ORDER BY c.name COLLATE NOCASE
            """,
            (book_id,),
        )
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in cursor.fetchall()
        ]

    # --- Device shelf state (SCHEMA_V12) -------------------------------

    def upsert_device_shelf_state(
        self,
        *,
        device_id: int,
        collection_id: int,
        shelf_id: str,
        shelf_name: str,
        last_pushed_at: str,
        book_count_on_device: int | None = None,
        member_hash: str | None = None,
    ) -> None:
        """Persist what we last pushed for a collection shelf.

        Mirrors device_read_state but for collection→shelf mappings.
        ``member_hash`` is a digest of the pushed membership so a later sync
        with no changes can skip the device write entirely.
        """
        self._conn.execute(
            """
            INSERT INTO device_shelf_state (
                device_id, collection_id, shelf_id, shelf_name,
                last_pushed_at, book_count_on_device, member_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id, collection_id) DO UPDATE SET
                shelf_id = excluded.shelf_id,
                shelf_name = excluded.shelf_name,
                last_pushed_at = excluded.last_pushed_at,
                book_count_on_device = excluded.book_count_on_device,
                member_hash = excluded.member_hash
            """,
            (
                device_id,
                collection_id,
                shelf_id,
                shelf_name,
                last_pushed_at,
                book_count_on_device,
                member_hash,
            ),
        )
        self._conn.commit()

    def get_collection_shelf_state(
        self, device_id: int, collection_id: int
    ) -> dict[str, object] | None:
        """Return the last-pushed shelf state for a collection on a device."""
        row = self._conn.execute(
            """
            SELECT device_id, collection_id, shelf_id, shelf_name,
                   last_pushed_at, book_count_on_device, member_hash
            FROM device_shelf_state
            WHERE device_id = ? AND collection_id = ?
            """,
            (device_id, collection_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "device_id": int(row["device_id"]),
            "collection_id": int(row["collection_id"]),
            "shelf_id": str(row["shelf_id"]),
            "shelf_name": str(row["shelf_name"]),
            "last_pushed_at": str(row["last_pushed_at"]),
            "book_count_on_device": row["book_count_on_device"],
            "member_hash": row["member_hash"],
        }

    def delete_collection_shelf_state(self, device_id: int, collection_id: int) -> None:
        """Remove the shelf state record for a collection on a device."""
        self._conn.execute(
            "DELETE FROM device_shelf_state WHERE device_id = ? AND collection_id = ?",
            (device_id, collection_id),
        )
        self._conn.commit()

    def list_collection_shelf_candidates(self, *, device_id: int) -> list[dict[str, object]]:
        """Return collections that can be pushed as shelves to a device.

        A collection is a candidate when at least one of its members (resolved via
        the single membership resolver, so rule-based collections are included even
        though they hold no ``collection_books`` rows) is present on the device.
        Each candidate carries its current on-device count, total member count, and
        any existing shelf state.
        """
        device_book_ids = {
            int(row["book_id"])
            for row in self._conn.execute(
                "SELECT book_id FROM device_files WHERE device_id = ?",
                (device_id,),
            )
        }
        if not device_book_ids:
            return []

        candidates: list[dict[str, object]] = []
        collection_rows = self._conn.execute(
            "SELECT id, name, updated_at FROM collections ORDER BY name COLLATE NOCASE"
        ).fetchall()
        for coll in collection_rows:
            collection_id = int(coll["id"])
            member_ids = self.resolve_collection_member_ids(collection_id)
            books_on_device = sum(1 for book_id in member_ids if book_id in device_book_ids)
            if books_on_device == 0:
                continue

            state = self._conn.execute(
                "SELECT shelf_id, last_pushed_at FROM device_shelf_state "
                "WHERE collection_id = ? AND device_id = ?",
                (collection_id, device_id),
            ).fetchone()
            candidates.append(
                {
                    "collection_id": collection_id,
                    "name": str(coll["name"]),
                    "updated_at": str(coll["updated_at"]),
                    "shelf_id": state["shelf_id"] if state is not None else None,
                    "last_pushed_at": state["last_pushed_at"] if state is not None else None,
                    "books_on_device": books_on_device,
                    "books_in_collection": len(member_ids),
                }
            )
        return candidates

    def list_collection_device_paths(self, *, collection_id: int, device_id: int) -> list[str]:
        """Return device remote paths for books in a collection that are on a device.

        Membership comes from the resolver (so it is correct for both static and
        rule-based collections); only members also present on the device (via
        ``device_files``) are returned, ordered deterministically. The caller
        turns these into Kobo ContentIDs by prefixing ``file://``.
        """
        member_ids = self.resolve_collection_member_ids(collection_id)
        if not member_ids:
            return []
        placeholders = ",".join("?" * len(member_ids))
        cursor = self._conn.execute(
            f"SELECT df.remote_path FROM device_files df "
            f"WHERE df.device_id = ? AND df.book_id IN ({placeholders}) "
            f"ORDER BY df.remote_path",
            [device_id, *member_ids],
        )
        return [str(row["remote_path"]) for row in cursor.fetchall()]

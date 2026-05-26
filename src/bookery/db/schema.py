# ABOUTME: SQL DDL statements for the Bookery library database schema.
# ABOUTME: Defines tables, indexes, FTS5 virtual table, and sync triggers.

SCHEMA_V1 = """
-- Core book catalog table
CREATE TABLE books (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    authors       TEXT,
    author_sort   TEXT,
    language      TEXT,
    publisher     TEXT,
    isbn          TEXT,
    description   TEXT,
    series        TEXT,
    series_index  REAL,
    identifiers   TEXT,
    source_path   TEXT NOT NULL,
    output_path   TEXT,
    file_hash     TEXT NOT NULL,
    date_added    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    date_modified TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE UNIQUE INDEX idx_books_file_hash ON books(file_hash);
CREATE INDEX idx_books_isbn ON books(isbn) WHERE isbn IS NOT NULL;
CREATE INDEX idx_books_series ON books(series) WHERE series IS NOT NULL;
CREATE INDEX idx_books_source_path ON books(source_path);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE books_fts USING fts5(
    title, authors, description, series,
    content='books',
    content_rowid='id'
);

-- Triggers to keep FTS in sync with the books table
CREATE TRIGGER books_ai AFTER INSERT ON books BEGIN
    INSERT INTO books_fts(rowid, title, authors, description, series)
    VALUES (new.id, new.title, new.authors, new.description, new.series);
END;

CREATE TRIGGER books_ad AFTER DELETE ON books BEGIN
    INSERT INTO books_fts(books_fts, rowid, title, authors, description, series)
    VALUES ('delete', old.id, old.title, old.authors, old.description, old.series);
END;

CREATE TRIGGER books_au AFTER UPDATE ON books BEGIN
    INSERT INTO books_fts(books_fts, rowid, title, authors, description, series)
    VALUES ('delete', old.id, old.title, old.authors, old.description, old.series);
    INSERT INTO books_fts(rowid, title, authors, description, series)
    VALUES (new.id, new.title, new.authors, new.description, new.series);
END;

-- Schema versioning for future migrations
CREATE TABLE schema_version (
    version    INTEGER NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

INSERT INTO schema_version (version) VALUES (1);
"""

SCHEMA_V2 = """
CREATE TABLE tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE INDEX idx_tags_name ON tags(name);

CREATE TABLE book_tags (
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (book_id, tag_id)
);
CREATE INDEX idx_book_tags_tag_id ON book_tags(tag_id);

INSERT INTO schema_version (version) VALUES (2);
"""

SCHEMA_V3 = """
CREATE TABLE genres (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

INSERT INTO genres (name) VALUES ('Literary Fiction');
INSERT INTO genres (name) VALUES ('Science Fiction');
INSERT INTO genres (name) VALUES ('Fantasy');
INSERT INTO genres (name) VALUES ('Mystery & Thriller');
INSERT INTO genres (name) VALUES ('Romance');
INSERT INTO genres (name) VALUES ('Horror');
INSERT INTO genres (name) VALUES ('Historical Fiction');
INSERT INTO genres (name) VALUES ('History & Biography');
INSERT INTO genres (name) VALUES ('Science & Technology');
INSERT INTO genres (name) VALUES ('Philosophy & Religion');
INSERT INTO genres (name) VALUES ('Self-Help & Personal Development');
INSERT INTO genres (name) VALUES ('Children''s & Middle Grade');
INSERT INTO genres (name) VALUES ('Young Adult');
INSERT INTO genres (name) VALUES ('Poetry & Drama');

CREATE TABLE book_genres (
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    genre_id   INTEGER NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
    is_primary INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (book_id, genre_id)
);
CREATE INDEX idx_book_genres_genre_id ON book_genres(genre_id);

ALTER TABLE books ADD COLUMN subjects TEXT;

INSERT INTO schema_version (version) VALUES (3);
"""

SCHEMA_V4 = """
ALTER TABLE books ADD COLUMN cover_url TEXT;
ALTER TABLE books ADD COLUMN published_date TEXT;
ALTER TABLE books ADD COLUMN original_publication_date TEXT;
ALTER TABLE books ADD COLUMN page_count INTEGER;

INSERT INTO schema_version (version) VALUES (4);
"""

SCHEMA_V5 = """
CREATE TABLE book_field_provenance (
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    confidence REAL,
    locked     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (book_id, field_name)
);
-- No separate book_id index: the PK (book_id, field_name) already makes
-- book_id the leftmost key, so SQLite uses it for WHERE book_id = ? lookups.

INSERT INTO schema_version (version) VALUES (5);
"""

SCHEMA_V6 = """
ALTER TABLE books ADD COLUMN subtitle TEXT;
ALTER TABLE books ADD COLUMN rating REAL;
ALTER TABLE books ADD COLUMN ratings_count INTEGER;
ALTER TABLE books ADD COLUMN print_type TEXT;
ALTER TABLE books ADD COLUMN maturity_rating TEXT;

INSERT INTO schema_version (version) VALUES (6);
"""

# Decouple "this book has been matched against a metadata provider" from
# "this book has a managed library location". Pre-V7, output_path served both
# meanings; after the library-canonical migration every row has output_path,
# so callers using `output_path IS NOT NULL` as a matched-flag broke silently.
#
# Backfill rule: a row counts as previously matched if it has at least one
# `book_field_provenance` entry written by a metadata provider — i.e. a source
# that isn't one of the internal/non-provider sources we know about
# (`extracted` for EPUB extraction inserts, `user` for manual edits via the
# CLI / web form, `genres` for the auto-genre applier). Anything else
# (`openlibrary`, `googlebooks`, `consensus:...`, future providers) is, by
# definition, evidence that a provider touched the row. This is more accurate
# than the `identifiers`-substring heuristic considered earlier, which both
# missed rows matched via web `enrich_apply` (which writes provenance but not
# the identifiers JSON) and produced false positives for Calibre EPUBs that
# already declared `<dc:identifier opf:scheme="ISBN">` (extraction stores
# those as `{"isbn": "..."}`).
#
# Backfilled rows take their date_modified (falling back to date_added) as a
# best-effort timestamp — provenance rows have their own `fetched_at`, but the
# books-table timestamps are the closest stable analogue for "when did the
# match-flow finish for this row" and avoid having to pick a single field's
# fetched_at.
SCHEMA_V7 = """
ALTER TABLE books ADD COLUMN metadata_matched_at TEXT;

UPDATE books
SET metadata_matched_at = COALESCE(date_modified, date_added)
WHERE id IN (
    SELECT DISTINCT book_id
    FROM book_field_provenance
    WHERE source NOT IN ('extracted', 'user', 'genres')
);

INSERT INTO schema_version (version) VALUES (7);
"""

# Bidirectional Kobo read-status layout. All four tables land together so
# P1b (catalog-side status writes) and P2 (device push, merge) are additive.
# `device_read_state` mirrors what we last pulled from the device; `book_status`
# is the catalog-side truth that user commands set; `device_files` records the
# on-device path of each kepub we copy, so the ContentID resolver becomes a
# direct primary-key lookup instead of recomputing sanitization rules.
SCHEMA_V8 = """
CREATE TABLE devices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    serial       TEXT NOT NULL,
    label        TEXT,
    last_seen_at TEXT,
    UNIQUE (kind, serial)
);

CREATE TABLE device_read_state (
    device_id          INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    book_id            INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    read_status        INTEGER NOT NULL,
    percent_read       REAL,
    last_read_at       TEXT,
    last_chapter_id    TEXT,
    status_updated_at  TEXT NOT NULL,
    pulled_at          TEXT NOT NULL,
    PRIMARY KEY (device_id, book_id)
);

CREATE TABLE book_status (
    book_id     INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    status      INTEGER NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE device_files (
    device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    book_id     INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    remote_path TEXT NOT NULL,
    written_at  TEXT NOT NULL,
    PRIMARY KEY (device_id, book_id)
);
CREATE INDEX idx_device_files_path ON device_files(device_id, remote_path);

INSERT INTO schema_version (version) VALUES (8);
"""

MIGRATIONS = [
    (2, SCHEMA_V2),
    (3, SCHEMA_V3),
    (4, SCHEMA_V4),
    (5, SCHEMA_V5),
    (6, SCHEMA_V6),
    (7, SCHEMA_V7),
    (8, SCHEMA_V8),
]

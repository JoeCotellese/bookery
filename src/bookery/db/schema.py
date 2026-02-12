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

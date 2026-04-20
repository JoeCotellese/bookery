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

MIGRATIONS = [
    (2, SCHEMA_V2),
    (3, SCHEMA_V3),
    (4, SCHEMA_V4),
    (5, SCHEMA_V5),
    (6, SCHEMA_V6),
]

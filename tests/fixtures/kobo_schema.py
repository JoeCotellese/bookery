# ABOUTME: Real Kobo KoboReader.sqlite shelf DDL, snapshotted verbatim from a device.
# ABOUTME: Shelf tests build their fake DB from this so they can't drift from hardware.

import sqlite3
from pathlib import Path

# DDL captured read-only from a real Kobo (/Volumes/KOBOeReader/.kobo/KoboReader.sqlite)
# on 2026-05-29. Kobo stores BOOL columns as the text values 'true'/'false', user shelves
# carry Type='UserTag', and ShelfContent links to a shelf by its Name (not its Id).
SHELF_DDL = """
CREATE TABLE Shelf (
    CreationDate TEXT,
    Id           TEXT,
    InternalName TEXT,
    LastModified TEXT,
    Name         TEXT,
    Type         TEXT,
    _IsDeleted   BOOL,
    _IsVisible   BOOL,
    _IsSynced    BOOL,
    _SyncTime    TEXT,
    LastAccessed TEXT,
    PRIMARY KEY(Id)
);
CREATE INDEX shelf_id_index ON shelf (Id);
CREATE INDEX shelf_name_index ON shelf (Name);
CREATE INDEX shelf_creationdate_index ON shelf (CreationDate);

CREATE TABLE ShelfContent (
    ShelfName    TEXT,
    ContentId    TEXT,
    DateModified TEXT,
    _IsDeleted   BOOL,
    _IsSynced    BOOL,
    PRIMARY KEY(ShelfName, ContentId)
);
CREATE INDEX shelfcontent_datemodified_index ON ShelfContent (DateModified);
"""


def make_fake_kobo_db(root: Path) -> Path:
    """Create a fake Kobo DB with the real shelf schema under ``<root>/.kobo``.

    Returns the path to KoboReader.sqlite. The layout mirrors a mounted device so
    callers can pass ``root`` as the sync target. Uses the default (DELETE) journal
    mode to match ``open_kobo_db_rw``, which never switches to WAL.
    """
    kobo_dir = root / ".kobo"
    kobo_dir.mkdir(parents=True, exist_ok=True)
    db_path = kobo_dir / "KoboReader.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SHELF_DDL)
        conn.commit()
    finally:
        conn.close()
    return db_path


def seed_shelf(
    db_path: Path,
    *,
    shelf_id: str,
    name: str,
    internal_name: str,
    shelf_type: str = "UserTag",
    is_deleted: str = "false",
    is_visible: str = "true",
) -> None:
    """Insert a pre-existing Shelf row (e.g. a user-created shelf for collision tests)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO Shelf (
                CreationDate, Id, InternalName, LastModified, Name, Type,
                _IsDeleted, _IsVisible, _IsSynced
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'false')
            """,
            (
                "2024-01-01T00:00:00",
                shelf_id,
                internal_name,
                "2024-01-01T00:00:00",
                name,
                shelf_type,
                is_deleted,
                is_visible,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def connect_ro(db_path: Path) -> sqlite3.Connection:
    """Open the fake Kobo DB with a Row factory for test assertions."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

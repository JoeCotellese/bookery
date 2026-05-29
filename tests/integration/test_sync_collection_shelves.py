# ABOUTME: Integration tests for collection shelf sync

import sqlite3
from pathlib import Path

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.device.kepub_cache import KepubCache
from bookery.device.kobo import sync_library_to_kobo
from bookery.metadata.types import BookMetadata


class _StubKepubify:
    def __init__(self) -> None:
        self.version = "v4.4.0"

    def run(self, epub: Path, *, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        result = out_dir / f"{epub.stem}.kepub.epub"
        result.write_bytes(b"FAKE-KEPUB")
        return result

    def get_version(self) -> str:
        return self.version


def _build_fake_kobo_mount(root: Path) -> Path:
    mount = root / "kobo"
    kobo_dir = mount / ".kobo"
    kobo_dir.mkdir(parents=True)
    (kobo_dir / "version").write_text("N428440071799,4.45.23684\n")
    return mount


def _seed_kobo_db_with_contentlist(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ContentType (
            ContentTypeID INTEGER PRIMARY KEY,
            Name TEXT NOT NULL
        );
        INSERT INTO ContentType (Name) VALUES ('eBook');
        
        CREATE TABLE IF NOT EXISTS Content (
            ContentID TEXT PRIMARY KEY,
            ContentType INTEGER REFERENCES ContentType(ContentTypeID),
            Title TEXT, Attribution TEXT, ReadStatus INTEGER DEFAULT 0,
            ___PercentRead REAL DEFAULT 0.0, DateLastRead TEXT,
            ChapterIDBookmarked TEXT, MimeType TEXT, BookID TEXT
        );
        
        CREATE TABLE IF NOT EXISTS ContentList (
            ContentListID TEXT PRIMARY KEY,
            ListName TEXT, ListType TEXT, ContentIDList TEXT,
            ___UserID TEXT, ___SyncTime TEXT,
            DateCreated TEXT, DateModified TEXT
        );
    """)
    conn.commit()
    conn.close()


def _add_library_book(library: Path, author: str, title: str) -> Path:
    epub = library / author / title / f"{title}.epub"
    epub.parent.mkdir(parents=True, exist_ok=True)
    epub.write_bytes(b"EPUB")
    return epub


def _add_catalog_book(catalog: LibraryCatalog, epub: Path, title: str, author: str) -> int:
    return catalog.add_book(
        BookMetadata(title=title, authors=[author], source_path=epub),
        file_hash=f"hash-{title}", output_path=epub,
    )


def _run_sync(catalog, mount, tmp_path, backup_root=None, status_push_enabled=True):
    return sync_library_to_kobo(
        catalog=catalog, target=mount,
        cache=KepubCache(tmp_path / "kepub.db"),
        run_kepubify=_StubKepubify().run,
        kepubify_version=_StubKepubify().get_version,
        workspace_dir=tmp_path / "workspace",
        books_subdir="Books", backup_root=backup_root,
        status_push_enabled=status_push_enabled,
    )


def test_collection_shelf_synced_to_device(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)

    library = tmp_path / "library"
    epub = _add_library_book(library, "Asimov", "Foundation")
    book_id = _add_catalog_book(catalog, epub, "Foundation", "Asimov")

    collection_id = catalog.create_collection("Favorites", "My favorite books")
    catalog.add_books_to_collection(collection_id, [book_id])

    mount = _build_fake_kobo_mount(tmp_path)
    kobo_db = mount / ".kobo" / "KoboReader.sqlite"
    _seed_kobo_db_with_contentlist(kobo_db)

    conn = sqlite3.connect(kobo_db)
    conn.execute(
        """
        INSERT INTO Content (ContentID, ContentType, Title, Attribution, MimeType)
        VALUES (?, 1, ?, ?, ?)
        """,
        (
            "file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub",
            "Foundation",
            "Asimov",
            "application/x-kobo-epub+zip",
        ),
    )
    conn.commit()
    conn.close()

    report = _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync1")

    assert report.shelves_pushed >= 1
    
    conn = sqlite3.connect(kobo_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM ContentList WHERE ListType = 'UserShelf'").fetchone()
    conn.close()

    assert row is not None
    assert row["ListName"] == "Favorites"


def test_shelf_state_persisted_in_catalog(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)

    library = tmp_path / "library"
    epub = _add_library_book(library, "Asimov", "Foundation")
    book_id = _add_catalog_book(catalog, epub, "Foundation", "Asimov")

    collection_id = catalog.create_collection("Favorites")
    catalog.add_books_to_collection(collection_id, [book_id])

    mount = _build_fake_kobo_mount(tmp_path)
    kobo_db = mount / ".kobo" / "KoboReader.sqlite"
    _seed_kobo_db_with_contentlist(kobo_db)

    _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync1")

    state = catalog.get_collection_shelf_state(1, collection_id)
    assert state is not None
    assert state["shelf_name"] == "Favorites"
    assert state["last_pushed_at"] is not None

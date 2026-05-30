# ABOUTME: Integration tests for collection shelf sync against the real Kobo schema.
# ABOUTME: Exercises sync_library_to_kobo end-to-end: membership, idempotency, orphan delete.

import sqlite3
from pathlib import Path

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.device.kepub_cache import KepubCache
from bookery.device.kobo import sync_library_to_kobo
from bookery.metadata.types import BookMetadata
from tests.fixtures.kobo_schema import make_fake_kobo_db


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
    """Build a mount with the real Shelf/ShelfContent schema and a version file."""
    mount = root / "kobo"
    kobo_dir = mount / ".kobo"
    kobo_dir.mkdir(parents=True)
    (kobo_dir / "version").write_text("N428440071799,4.45.23684\n")
    make_fake_kobo_db(mount)
    return mount


def _add_library_book(library: Path, author: str, title: str) -> Path:
    epub = library / author / title / f"{title}.epub"
    epub.parent.mkdir(parents=True, exist_ok=True)
    epub.write_bytes(b"EPUB")
    return epub


def _add_catalog_book(catalog: LibraryCatalog, epub: Path, title: str, author: str) -> int:
    return catalog.add_book(
        BookMetadata(title=title, authors=[author], source_path=epub),
        file_hash=f"hash-{title}",
        output_path=epub,
    )


def _run_sync(catalog, mount, tmp_path, backup_root=None, status_push_enabled=True):
    return sync_library_to_kobo(
        catalog=catalog,
        target=mount,
        cache=KepubCache(tmp_path / "kepub.db"),
        run_kepubify=_StubKepubify().run,
        kepubify_version=_StubKepubify().get_version,
        workspace_dir=tmp_path / "workspace",
        books_subdir="Books",
        backup_root=backup_root,
        status_push_enabled=status_push_enabled,
    )


def _shelf_db(mount: Path) -> Path:
    return mount / ".kobo" / "KoboReader.sqlite"


def _query(db_path: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def test_collection_shelf_synced_to_device(tmp_path: Path) -> None:
    """A collection becomes a Shelf row + ShelfContent rows on the device."""
    conn = open_library(tmp_path / "library.db")
    catalog = LibraryCatalog(conn)

    library = tmp_path / "library"
    epub = _add_library_book(library, "Asimov", "Foundation")
    book_id = _add_catalog_book(catalog, epub, "Foundation", "Asimov")

    collection_id = catalog.create_collection("Favorites", "My favorite books")
    catalog.add_books_to_collection(collection_id, [book_id])

    mount = _build_fake_kobo_mount(tmp_path)
    report = _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync1")

    assert report.shelves_pushed >= 1

    shelves = _query(
        _shelf_db(mount),
        "SELECT * FROM Shelf WHERE InternalName = ?",
        (f"bookery-{collection_id}",),
    )
    assert len(shelves) == 1
    assert shelves[0]["Name"] == "Favorites"
    assert shelves[0]["Type"] == "UserTag"

    # ShelfContent links by InternalName (what nickel joins on), not display name.
    content = _query(
        _shelf_db(mount),
        "SELECT ContentId FROM ShelfContent WHERE ShelfName = ?",
        (f"bookery-{collection_id}",),
    )
    assert [row["ContentId"] for row in content] == [
        "file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub"
    ]


def test_shelf_state_persisted_with_member_hash(tmp_path: Path) -> None:
    """Shelf state, including member_hash, is persisted back to the catalog."""
    conn = open_library(tmp_path / "library.db")
    catalog = LibraryCatalog(conn)

    library = tmp_path / "library"
    epub = _add_library_book(library, "Asimov", "Foundation")
    book_id = _add_catalog_book(catalog, epub, "Foundation", "Asimov")
    collection_id = catalog.create_collection("Favorites")
    catalog.add_books_to_collection(collection_id, [book_id])

    mount = _build_fake_kobo_mount(tmp_path)
    _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync1")

    state = catalog.get_collection_shelf_state(1, collection_id)
    assert state is not None
    assert state["shelf_name"] == "Favorites"
    assert state["last_pushed_at"] is not None
    assert state["member_hash"]  # non-empty digest stored


def test_membership_is_per_collection(tmp_path: Path) -> None:
    """Each shelf gets only its own collection's books, not every device book."""
    conn = open_library(tmp_path / "library.db")
    catalog = LibraryCatalog(conn)

    library = tmp_path / "library"
    foundation = _add_catalog_book(
        catalog, _add_library_book(library, "Asimov", "Foundation"), "Foundation", "Asimov"
    )
    dune = _add_catalog_book(
        catalog, _add_library_book(library, "Herbert", "Dune"), "Dune", "Herbert"
    )

    sci_fi = catalog.create_collection("Sci-Fi")
    classics = catalog.create_collection("Classics")
    catalog.add_books_to_collection(sci_fi, [foundation])
    catalog.add_books_to_collection(classics, [dune])

    mount = _build_fake_kobo_mount(tmp_path)
    _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync1")

    sci_fi_content = _query(
        _shelf_db(mount),
        "SELECT ContentId FROM ShelfContent WHERE ShelfName = ?",
        (f"bookery-{sci_fi}",),
    )
    classics_content = _query(
        _shelf_db(mount),
        "SELECT ContentId FROM ShelfContent WHERE ShelfName = ?",
        (f"bookery-{classics}",),
    )
    assert [r["ContentId"] for r in sci_fi_content] == [
        "file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub"
    ]
    assert [r["ContentId"] for r in classics_content] == [
        "file:///mnt/onboard/Books/Herbert/Dune/Dune.kepub.epub"
    ]


def test_resync_with_no_changes_is_noop(tmp_path: Path) -> None:
    """A second sync with no membership change skips the device write (member_hash)."""
    conn = open_library(tmp_path / "library.db")
    catalog = LibraryCatalog(conn)

    library = tmp_path / "library"
    epub = _add_library_book(library, "Asimov", "Foundation")
    book_id = _add_catalog_book(catalog, epub, "Foundation", "Asimov")
    collection_id = catalog.create_collection("Favorites")
    catalog.add_books_to_collection(collection_id, [book_id])

    mount = _build_fake_kobo_mount(tmp_path)
    first = _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync1")
    assert first.shelves_pushed >= 1

    second = _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync2")
    assert second.shelves_pushed == 0


def test_deleting_collection_removes_shelf(tmp_path: Path) -> None:
    """Deleting a collection removes its shelf from the device on the next sync."""
    conn = open_library(tmp_path / "library.db")
    catalog = LibraryCatalog(conn)

    library = tmp_path / "library"
    epub = _add_library_book(library, "Asimov", "Foundation")
    book_id = _add_catalog_book(catalog, epub, "Foundation", "Asimov")
    collection_id = catalog.create_collection("Favorites")
    catalog.add_books_to_collection(collection_id, [book_id])

    mount = _build_fake_kobo_mount(tmp_path)
    _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync1")
    assert _query(
        _shelf_db(mount),
        "SELECT 1 FROM Shelf WHERE InternalName = ?",
        (f"bookery-{collection_id}",),
    )

    catalog.delete_collection(collection_id)
    report = _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync2")

    assert "Favorites" in report.shelves_deleted
    assert (
        _query(
            _shelf_db(mount),
            "SELECT 1 FROM Shelf WHERE InternalName = ?",
            (f"bookery-{collection_id}",),
        )
        == []
    )

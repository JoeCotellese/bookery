# ABOUTME: Read-only access to a mounted Kobo's KoboReader.sqlite — pulls read
# ABOUTME: status into the bookery catalog. No device writes happen here.
#
# Verification reference: Kobo Libra Colour family (device prefix N428440071799),
# firmware 4.45.23684, 2026-05-26. Schema fields and connection URI flags below
# were validated against a real device with 1146 sideloaded books.

import logging
import sqlite3
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KoboContentRow:
    """One row from the device `content` table — a top-level book record."""

    content_id: str
    read_status: int  # 0 unread, 1 reading, 2 finished
    percent_read: float | None
    date_last_read: str | None
    chapter_id_bookmarked: str | None
    mime_type: str


def open_kobo_db(kobo_sqlite_path: Path) -> sqlite3.Connection:
    """Open KoboReader.sqlite read-only with `immutable=1`.

    Plain ``?mode=ro`` fails on a USB-mounted Kobo with "unable to open
    database file" because SQLite still tries to open a rollback journal for
    crash recovery — which needs write access the mount won't grant.
    ``immutable=1`` declares the file unchanging during the read window, so
    SQLite skips the journal entirely. This is the single most important
    detail in the whole reader module.
    """
    uri = f"file:{kobo_sqlite_path}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def read_content_rows(conn: sqlite3.Connection) -> list[KoboContentRow]:
    """Return top-level book rows (chapter rows excluded) with EPUB/kepub mime.

    ``BookID IS NULL`` filters out the chapter rows that Kobo nests under each
    book; ``MimeType LIKE 'application/%epub%'`` catches both the common kepub
    (``application/x-kobo-epub+zip``) and raw EPUB (``application/epub+zip``)
    sideloads, while excluding PDFs and store-only content.
    """
    cursor = conn.execute(
        """
        SELECT ContentID,
               ReadStatus,
               ___PercentRead,
               DateLastRead,
               ChapterIDBookmarked,
               MimeType
        FROM content
        WHERE BookID IS NULL
          AND MimeType LIKE 'application/%epub%'
        """
    )
    return [
        KoboContentRow(
            content_id=row[0],
            read_status=int(row[1] or 0),
            percent_read=float(row[2]) if row[2] is not None else None,
            date_last_read=row[3],
            chapter_id_bookmarked=row[4],
            mime_type=row[5],
        )
        for row in cursor.fetchall()
    ]


def _normalize_content_id(content_id: str) -> str:
    """Strip a ``file://`` scheme and URL-decode percent escapes.

    Kobo Libra Colour firmware 4.45.23684 stores ContentID *un*encoded, but
    older firmwares may URL-encode spaces and punctuation. ``unquote`` is a
    safe no-op when there's nothing to decode, so we always run it. Non-file
    schemes (newsstand, store) pass through untouched — callers decide whether
    to filter them.
    """
    if content_id.startswith("file://"):
        path = content_id[len("file://") :]
        return urllib.parse.unquote(path)
    return content_id


def read_kobo_serial(mount_path: Path) -> str:
    """Read the device serial from ``<mount>/.kobo/version``.

    The version file is a comma-separated list whose first field is the
    serial-like device identifier (e.g. ``N428440071799``). If the file
    contains no comma, return the whole stripped content — useful for older
    devices or alternate firmwares where the format differs.
    """
    version_file = mount_path / ".kobo" / "version"
    text = version_file.read_text().strip()
    first, sep, _ = text.partition(",")
    return first if sep else text


class _ReaderCatalogProto(Protocol):
    def resolve_book_id_for_remote_path(
        self, *, device_id: int, remote_path: str
    ) -> int | None: ...

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
    ) -> None: ...

    def merge_book_status_from_device(
        self,
        *,
        book_id: int,
        device_status: int,
        device_updated_at: str,
    ) -> None: ...


def pull_read_state(
    catalog: _ReaderCatalogProto,
    *,
    device_id: int,
    mount_path: Path,
    now: str,
) -> tuple[int, int]:
    """Pull read-state rows from the device and merge into the catalog.

    Returns ``(pulled, skipped)`` — the number of rows whose ContentID
    resolved to a known book in our catalog, and the number that didn't
    (and were therefore ignored).

    ``device_read_state`` is mirrored unconditionally — it always reflects
    the device's most recent reality. ``book_status`` goes through the
    timestamp-aware merge in :meth:`LibraryCatalog.merge_book_status_from_device`:
    device-newer-or-equal overwrites catalog, catalog-newer keeps the user's
    bookery read/unread/reading intent intact. The push half of the sync
    (in :mod:`bookery.device.kobo`) handles the reverse direction.

    Best-effort: a missing or unreadable KoboReader.sqlite logs a warning and
    returns ``(0, 0)`` rather than raising — a Kobo with no read history yet
    or a transient mount issue must not fail the kepub-copy half of a sync.
    """
    db_path = mount_path / ".kobo" / "KoboReader.sqlite"
    if not db_path.exists():
        logger.warning("KoboReader.sqlite not found at %s; skipping read-state pull", db_path)
        return (0, 0)

    try:
        conn = open_kobo_db(db_path)
    except sqlite3.Error as exc:
        logger.warning("Could not open KoboReader.sqlite at %s: %s", db_path, exc)
        return (0, 0)

    try:
        rows = read_content_rows(conn)
    except sqlite3.Error as exc:
        logger.warning("Could not read content rows from %s: %s", db_path, exc)
        return (0, 0)
    finally:
        conn.close()

    pulled = 0
    skipped = 0
    for row in rows:
        remote_path = _normalize_content_id(row.content_id)
        book_id = catalog.resolve_book_id_for_remote_path(
            device_id=device_id, remote_path=remote_path
        )
        if book_id is None:
            skipped += 1
            continue
        # status_updated_at falls back to `now` when the device has never
        # recorded a DateLastRead (an unread book that's been on-device since
        # before tracking started). The merge logic in P2 keys on this field,
        # so it must always be a real ISO timestamp.
        status_updated_at = row.date_last_read or now
        catalog.upsert_device_read_state(
            device_id=device_id,
            book_id=book_id,
            read_status=row.read_status,
            percent_read=row.percent_read,
            last_read_at=row.date_last_read,
            last_chapter_id=row.chapter_id_bookmarked,
            status_updated_at=status_updated_at,
            pulled_at=now,
        )
        catalog.merge_book_status_from_device(
            book_id=book_id,
            device_status=row.read_status,
            device_updated_at=status_updated_at,
        )
        pulled += 1
    return (pulled, skipped)

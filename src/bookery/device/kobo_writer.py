# ABOUTME: Read-write access to a mounted Kobo's KoboReader.sqlite — pushes read
# ABOUTME: status from the bookery catalog into the device. The only module that
# ABOUTME: mutates KoboReader.sqlite.
#
# Verification reference: Kobo Libra Colour family (device prefix N428440071799),
# firmware 4.45.23684, 2026-05-26. ContentID format and writable columns below
# were validated against a real device.

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from bookery.db.status import STATUS_FINISHED, STATUS_READING, STATUS_UNREAD

logger = logging.getLogger(__name__)


# The writer touches only these columns on the device's ``content`` table.
# Keeping this set tiny is a defensive boundary: if a refactor ever tries to
# write ___SyncTime / ___UserID / Synced / etc., the build of the UPDATE
# statement happens here and only here, so the allow-list is single-source.
_ALLOWED_COLUMNS = frozenset({"ReadStatus", "___PercentRead", "DateLastRead"})


@dataclass(frozen=True, slots=True)
class ReadStatusUpdate:
    """One row's worth of intent: push ``status`` for ``content_id``.

    ``content_id`` is the exact KoboReader.sqlite ``ContentID`` value
    (typically ``file:///mnt/onboard/Books/Author/Title.kepub.epub``).
    ``status`` is one of ``STATUS_UNREAD``/``STATUS_READING``/``STATUS_FINISHED``.
    """

    content_id: str
    status: int


@dataclass
class PushReport:
    """Outcome of a ``push_read_status`` batch.

    ``pushed_count`` is rows whose UPDATE actually changed a device row.
    ``pull_only_count`` is rows whose ContentID had no match on the device
    (e.g. a book bookery copied this sync that the firmware hasn't indexed
    yet). ``failed`` is ContentID + error-message pairs from a rollback
    scenario — present iff the transaction aborted.
    """

    pushed_count: int = 0
    pull_only_count: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def open_kobo_db_rw(kobo_sqlite_path: Path) -> sqlite3.Connection:
    """Open KoboReader.sqlite in read-write mode.

    ``mode=rw`` requires the file to exist — SQLite raises
    ``OperationalError`` if it doesn't, which is the behaviour we want
    (silently creating an empty KoboReader.sqlite on a missing device would
    mask a real problem). The connection uses the default journal mode
    (DELETE); we intentionally do not switch to WAL because the Kobo firmware
    only knows about rollback journals.
    """
    uri = f"file:{kobo_sqlite_path}?mode=rw"
    return sqlite3.connect(uri, uri=True)


def _percent_for_status(status: int) -> float | None:
    """Translate a status int into a ``___PercentRead`` value or None for skip.

    Finished → 100.0; unread → 0.0; reading → None means "don't touch the
    column at all" — the user might be mid-book and we don't want to clobber
    the device's own percentage tracking with a guess.
    """
    if status == STATUS_FINISHED:
        return 100.0
    if status == STATUS_UNREAD:
        return 0.0
    if status == STATUS_READING:
        return None
    raise ValueError(f"Unsupported status int: {status}")


def push_read_status(
    *,
    db_path: Path,
    updates: list[ReadStatusUpdate],
    now: Callable[[], str],
) -> PushReport:
    """Apply read-status updates to KoboReader.sqlite in a single transaction.

    For each update we run an UPDATE keyed on ContentID, touching only the
    columns in :data:`_ALLOWED_COLUMNS`. Every row pushed gets
    ``DateLastRead = now()`` — this closes the "user opened the book after I
    marked it" hole described in #178's sync model. ``___PercentRead`` follows
    :func:`_percent_for_status`.

    Single transaction: if any UPDATE raises ``sqlite3.Error`` the whole batch
    rolls back (verified via file hash in tests), and the failure list comes
    back to the caller so the sync report can surface which books didn't
    make it. A row whose ContentID isn't on the device (UPDATE affects zero
    rows) is *not* a failure — it just means the firmware hasn't indexed it
    yet — so it lands in ``pull_only_count`` instead.
    """
    report = PushReport()
    if not updates:
        return report

    timestamp = now()
    conn = open_kobo_db_rw(db_path)
    try:
        # Explicit transaction so a mid-batch failure rolls back cleanly.
        # sqlite3's default isolation already wraps DML, but BEGIN makes the
        # intent obvious to readers and to the rollback path below.
        conn.execute("BEGIN")
        try:
            for upd in updates:
                percent = _percent_for_status(upd.status)
                # Build the SET clause from the allow-list — never let column
                # names from anywhere else into the SQL.
                set_parts = ["ReadStatus = ?", "DateLastRead = ?"]
                params: list[object] = [upd.status, timestamp]
                if percent is not None:
                    set_parts.append("___PercentRead = ?")
                    params.append(percent)
                # Sanity check the allow-list invariant — column names are
                # literals above so this is a tripwire for future edits, not
                # a runtime guard against user input.
                for clause in set_parts:
                    col = clause.split(" ", 1)[0]
                    assert col in _ALLOWED_COLUMNS, (
                        f"Writer tried to touch disallowed column {col!r}"
                    )

                params.append(upd.content_id)
                cursor = conn.execute(
                    f"UPDATE content SET {', '.join(set_parts)} WHERE ContentID = ?",
                    params,
                )
                if cursor.rowcount > 0:
                    report.pushed_count += 1
                else:
                    report.pull_only_count += 1
        except sqlite3.Error as exc:
            conn.execute("ROLLBACK")
            logger.warning(
                "Read-status push failed; rolling back batch of %d update(s): %s",
                len(updates),
                exc,
            )
            report.pushed_count = 0
            report.pull_only_count = 0
            report.failed = [(upd.content_id, str(exc)) for upd in updates]
            return report
        conn.execute("COMMIT")
    finally:
        conn.close()
    return report

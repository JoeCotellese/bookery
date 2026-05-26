# ABOUTME: Read-write access to a mounted Kobo's KoboReader.sqlite — pushes read
# ABOUTME: status from the bookery catalog into the device. The only module that
# ABOUTME: mutates KoboReader.sqlite.
#
# Verification reference: Kobo Libra Colour family (device prefix N428440071799),
# firmware 4.45.23684, 2026-05-26. ContentID format and writable columns below
# were validated against a real device.

import sqlite3
from pathlib import Path


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

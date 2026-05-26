# ABOUTME: Snapshot KoboReader.sqlite before any mutating sync — one file per
# ABOUTME: device per day, with rotation to the 14 most recent. Cheap and quiet.

import datetime as _dt
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Keep two weeks of daily snapshots per device. Bounded but generous; a Kobo
# DB is small enough (a few MB) that 14 files won't fill the user's disk.
ROTATION_KEEP = 14


def backup_kobo_db(
    *,
    source_db: Path,
    backup_root: Path,
    device_serial: str,
    now: _dt.datetime,
) -> Path | None:
    """Copy KoboReader.sqlite to ``<backup_root>/<serial>/<YYYY-MM-DD>-<HHMMSS>.sqlite``.

    Idempotent per device-day: if any snapshot from today already exists, the
    function returns its path and does not re-copy — the contract is "first
    mutating sync per device-day takes the snapshot", not "every sync takes
    one". This keeps the backup dir uncluttered when the user syncs multiple
    times an hour.

    Rotation: after writing, prunes everything older than the 14 most recent
    files in the device's directory. Best-effort throughout — a missing
    source file, a corrupted backup dir, or an OS error logs a warning and
    returns ``None`` rather than blocking the sync.
    """
    if not source_db.exists():
        logger.warning("Skipping Kobo DB backup: source missing at %s", source_db)
        return None

    device_dir = backup_root / device_serial
    try:
        device_dir.mkdir(parents=True, exist_ok=True)
    except (NotADirectoryError, FileExistsError, OSError) as exc:
        logger.warning(
            "Could not prepare backup dir at %s: %s", device_dir, exc
        )
        return None

    # Same-day idempotency: any file whose name starts with today's date
    # short-circuits the copy. We don't care about the time suffix — the
    # earliest snapshot of the day is the one we want to preserve.
    date_prefix = now.strftime("%Y-%m-%d")
    try:
        existing_today = sorted(
            p for p in device_dir.iterdir() if p.name.startswith(date_prefix)
        )
    except OSError as exc:
        logger.warning("Could not list backup dir %s: %s", device_dir, exc)
        return None
    if existing_today:
        return existing_today[0]

    stamp = now.strftime("%Y-%m-%d-%H%M%S")
    dest = device_dir / f"{stamp}.sqlite"
    try:
        shutil.copyfile(source_db, dest)
    except OSError as exc:
        logger.warning("Could not write Kobo DB backup to %s: %s", dest, exc)
        return None

    _rotate(device_dir)
    return dest


def _rotate(device_dir: Path) -> None:
    """Trim the device's backup directory to the ``ROTATION_KEEP`` most recent files.

    Sorting by filename works because we stamp ``YYYY-MM-DD-HHMMSS`` which
    is lexicographically ordered. Failures are swallowed — rotation is a
    nice-to-have, not a blocking step.
    """
    try:
        files = sorted(p for p in device_dir.iterdir() if p.is_file())
    except OSError:
        return
    excess = len(files) - ROTATION_KEEP
    if excess <= 0:
        return
    for old in files[:excess]:
        try:
            old.unlink()
        except OSError as exc:
            logger.warning("Could not rotate old backup %s: %s", old, exc)

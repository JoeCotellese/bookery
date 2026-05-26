# ABOUTME: Kobo device sync — detects mounted readers and copies kepubs to them.
# ABOUTME: The library stays canonical EPUB; kepubify runs only inside this module.

import contextlib
import datetime as _dt
import getpass
import logging
import platform
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from bookery.core.pathformat import sanitize_component
from bookery.db.hashing import compute_file_hash
from bookery.db.mapping import BookRecord
from bookery.db.status import PushCandidate
from bookery.device.kobo_backup import backup_kobo_db
from bookery.device.kobo_reader import pull_read_state, read_kobo_serial
from bookery.device.kobo_writer import ReadStatusUpdate, push_read_status

KOBO_MARKER = ".kobo"

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    # UTC to match SQLite's `strftime('%Y-%m-%dT%H:%M:%S', 'now')` used
    # elsewhere in the catalog — keeps merge timestamps comparable.
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0, tzinfo=None).isoformat()


# The Kobo mounts its internal storage at `/mnt/onboard` from its own
# perspective; the host sees the same root as the user-chosen `target` mount.
# ContentID in KoboReader.sqlite is always written from the device's view, so
# device_files must record paths in that same coordinate system — otherwise
# the resolver's PK lookup misses every real-world row.
KOBO_DEVICE_ROOT = "/mnt/onboard"


def _to_device_path(host_path: Path, target: Path) -> str:
    """Translate a host-side absolute path into the Kobo's `/mnt/onboard/...` form."""
    relative = host_path.relative_to(target)
    return f"{KOBO_DEVICE_ROOT}/{relative.as_posix()}"


def _default_mount_roots() -> list[Path]:
    system = platform.system()
    if system == "Darwin":
        return [Path("/Volumes")]
    if system == "Linux":
        try:
            user = getpass.getuser()
        except Exception:
            user = ""
        roots = [Path("/media"), Path("/mnt")]
        if user:
            roots.extend([Path(f"/media/{user}"), Path(f"/run/media/{user}")])
        return roots
    return []


def _scan_roots(roots: Iterable[Path]) -> list[Path]:
    candidates: list[Path] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir():
                candidates.append(child)
    return candidates


def detect_mounted_kobo(*, candidates: Iterable[Path] | None = None) -> Path | None:
    """Return the first mount path that contains a `.kobo/` marker, else None.

    When `candidates` is None, scans platform-default mount roots (e.g.
    /Volumes on macOS; /media/$USER and /run/media/$USER on Linux).
    """
    if candidates is None:
        candidates = _scan_roots(_default_mount_roots())
    for path in candidates:
        if not path.exists():
            continue
        if (path / KOBO_MARKER).is_dir():
            return path
    return None


@dataclass
class SyncReport:
    copied: list[Path] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    read_states_pulled: int = 0
    read_states_skipped: int = 0
    # P2: device-side write counts. ``read_statuses_pushed`` is rows we
    # actually mutated on the Kobo; ``read_status_pull_only`` is push
    # candidates whose ContentID didn't match a current device row (book
    # copied this sync but not yet indexed by firmware); ``read_status_push_failed``
    # is (content_id, error_message) pairs from a rollback scenario.
    read_statuses_pushed: int = 0
    read_status_pull_only: int = 0
    read_status_push_failed: list[tuple[str, str]] = field(default_factory=list)
    backup_path: Path | None = None


class _CatalogProto(Protocol):
    def list_all(self) -> list[BookRecord]: ...

    def upsert_device(self, *, kind: str, serial: str, label: str | None, now: str) -> int: ...

    def upsert_device_file(
        self, *, device_id: int, book_id: int, remote_path: str, now: str
    ) -> None: ...

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
        self, *, book_id: int, device_status: int, device_updated_at: str
    ) -> None: ...

    def list_push_candidates(self, *, device_id: int) -> list[PushCandidate]: ...


class _CacheProto(Protocol):
    def get(self, source_hash: str, kepubify_version: str) -> str | None: ...

    def put(
        self,
        source_hash: str,
        kepubify_version: str,
        kepub_sha: str,
        device_path: Path,
    ) -> None: ...


ProgressCallback = Callable[[int, int, BookRecord], None]
StageCallback = Callable[[str], None]


def _book_dest_dir(target: Path, books_subdir: str, record: BookRecord) -> Path:
    author_raw = record.metadata.authors[0] if record.metadata.authors else "Unknown Author"
    title_raw = record.metadata.title or "Untitled"
    author = sanitize_component(author_raw, fallback="Unknown Author")
    title = sanitize_component(title_raw, fallback="Untitled")
    return target / books_subdir / author / title


def _sync_record(
    record: BookRecord,
    *,
    target: Path,
    books_subdir: str,
    cache: _CacheProto,
    version: str,
    run_kepubify: Callable[..., Path],
    workspace: Path,
    report: SyncReport,
    catalog: _CatalogProto,
    device_id: int | None,
    now: str,
    on_stage: StageCallback | None = None,
) -> None:
    def stage(name: str) -> None:
        if on_stage is not None:
            on_stage(name)

    source = record.output_path
    if source is None:
        report.skipped.append((record.source_path, "no canonical EPUB in library"))
        return
    if source.suffix.lower() != ".epub":
        report.skipped.append((source, "output is not an EPUB"))
        return
    if not source.exists():
        report.failed.append((source, f"source missing: {source}"))
        return

    dest_dir = _book_dest_dir(target, books_subdir, record)
    title = sanitize_component(record.metadata.title, fallback="Untitled")
    dest = dest_dir / f"{title}.kepub.epub"

    stage("hash")
    try:
        source_hash = compute_file_hash(source)
    except OSError as exc:
        report.failed.append((source, f"hash failed: {exc}"))
        return

    cached_kepub_sha = cache.get(source_hash, version)
    if cached_kepub_sha is not None and dest.exists():
        try:
            if compute_file_hash(dest) == cached_kepub_sha:
                stage("cached")
                report.skipped.append((dest, "already up to date"))
                return
        except OSError:
            pass  # fall through to re-convert

    stage("convert")
    try:
        kepub_path = run_kepubify(source, out_dir=workspace)
    except Exception as exc:
        report.failed.append((source, f"kepubify error: {exc}"))
        return

    stage("copy")
    try:
        kepub_sha = compute_file_hash(kepub_path)
        dest_dir.mkdir(parents=True, exist_ok=True)
        # shutil.move handles cross-device renames and streams large files.
        shutil.move(str(kepub_path), str(dest))
    except OSError as exc:
        report.failed.append((source, f"copy failed: {exc}"))
        return

    cache.put(source_hash, version, kepub_sha, dest)
    stage("done")
    report.copied.append(dest)
    if device_id is not None:
        catalog.upsert_device_file(
            device_id=device_id,
            book_id=record.id,
            remote_path=_to_device_path(dest, target),
            now=now,
        )


def _build_push_updates(candidates: list[PushCandidate]) -> list[ReadStatusUpdate]:
    """Filter push candidates down to the ones the catalog wins for.

    A candidate becomes a push when the catalog's ``updated_at`` is strictly
    greater than the device's ``status_updated_at`` (or the device has no row
    for the book at all). Equal-or-older candidates are dropped — the pull
    half already converged those rows via :func:`merge_book_status_from_device`.
    Returns ``ReadStatusUpdate`` instances keyed on the device ContentID,
    which is ``file://`` + ``remote_path``.
    """
    updates: list[ReadStatusUpdate] = []
    for cand in candidates:
        if (
            cand.device_status_updated_at is not None
            and cand.catalog_updated_at <= cand.device_status_updated_at
        ):
            continue
        content_id = f"file://{cand.remote_path}"
        updates.append(
            ReadStatusUpdate(content_id=content_id, status=cand.catalog_status)
        )
    return updates


def _push_read_state(
    *,
    catalog: _CatalogProto,
    device_id: int,
    target: Path,
    serial: str,
    backup_root: Path | None,
    report: SyncReport,
) -> None:
    """Apply catalog-side status to the device DB.

    Runs after the kepub copy phase so ``device_files`` reflects the books
    actually on the device. Builds a push list via
    :func:`_build_push_updates`, takes a backup snapshot if there's anything
    to write, then hands off to :func:`push_read_status`. All failures are
    swallowed into the report rather than raised — the pull half of the
    sync has already done useful work and we don't want to throw it away.
    """
    try:
        candidates = catalog.list_push_candidates(device_id=device_id)
    except Exception as exc:
        logger.warning("Could not list push candidates: %s", exc)
        return
    updates = _build_push_updates(candidates)
    if not updates:
        return

    db_path = target / ".kobo" / "KoboReader.sqlite"
    if not db_path.exists():
        logger.warning(
            "KoboReader.sqlite not found at %s; skipping read-status push", db_path
        )
        return

    if backup_root is not None:
        report.backup_path = backup_kobo_db(
            source_db=db_path,
            backup_root=backup_root,
            device_serial=serial,
            now=_dt.datetime.now(_dt.UTC),
        )

    try:
        push = push_read_status(
            db_path=db_path,
            updates=updates,
            now=_now_iso,
        )
    except Exception as exc:
        logger.warning("Read-status push failed: %s", exc)
        report.read_status_push_failed = [
            (upd.content_id, str(exc)) for upd in updates
        ]
        return
    report.read_statuses_pushed = push.pushed_count
    report.read_status_pull_only = push.pull_only_count
    report.read_status_push_failed = list(push.failed)


def sync_library_to_kobo(
    *,
    catalog: _CatalogProto,
    target: Path,
    cache: _CacheProto,
    run_kepubify: Callable[..., Path],
    kepubify_version: Callable[[], str],
    workspace_dir: Path,
    books_subdir: str = "Bookery",
    dry_run: bool = False,
    on_progress: ProgressCallback | None = None,
    on_stage: StageCallback | None = None,
    backup_root: Path | None = None,
    status_push_enabled: bool = True,
) -> SyncReport:
    """Walk the catalog and mirror its EPUBs to a Kobo as .kepub.epub files.

    Cache semantics: row keyed on (source_sha256, kepubify_version) -> kepub_sha
    plus the device-side path that kepub was written to. On re-sync we hash
    the on-device file; if it matches the cached kepub_sha we skip kepubify
    entirely. Cache miss or device-file mismatch triggers a fresh run.

    Dependencies are injected so this function stays unit-testable; the CLI
    wires up the real KepubCache and the kepubify subprocess wrapper.
    `workspace_dir` is where kepubify writes intermediate files before they
    are moved onto the device; the CLI scopes it to the bookery data dir so
    we never touch the device mount's parent (e.g. /Volumes itself).
    """
    report = SyncReport()
    records = catalog.list_all()
    total = len(records)
    if dry_run:
        for idx, record in enumerate(records, 1):
            if on_progress is not None:
                on_progress(idx, total, record)
            source = record.output_path
            if source is None:
                report.skipped.append((record.source_path, "no canonical EPUB in library"))
                continue
            if source.suffix.lower() != ".epub":
                report.skipped.append((source, "output is not an EPUB"))
                continue
            dest_dir = _book_dest_dir(target, books_subdir, record)
            title = sanitize_component(record.metadata.title, fallback="Untitled")
            report.copied.append(dest_dir / f"{title}.kepub.epub")
        return report

    version = kepubify_version()
    workspace_dir.mkdir(parents=True, exist_ok=True)
    now = _now_iso()

    # Device identity + read-state pull happen before the kepub loop so the
    # device DB is read in a clean (pre-write) window. All three phases
    # (pull / copy / push) are best-effort — a missing `.kobo/version` or
    # unreadable KoboReader.sqlite logs a warning but never aborts the
    # kepub copy half of the sync.
    device_id: int | None = None
    serial: str | None = None
    try:
        serial = read_kobo_serial(target)
    except FileNotFoundError:
        logger.warning(
            "%s/.kobo/version not found; skipping device-state pull",
            target,
        )
    if serial is not None:
        device_id = catalog.upsert_device(kind="kobo", serial=serial, label=None, now=now)
        try:
            pulled, skipped = pull_read_state(
                catalog, device_id=device_id, mount_path=target, now=now
            )
            report.read_states_pulled = pulled
            report.read_states_skipped = skipped
        except Exception as exc:
            logger.warning("Read-state pull failed; continuing with copy: %s", exc)

    try:
        for idx, record in enumerate(records, 1):
            if on_progress is not None:
                on_progress(idx, total, record)
            _sync_record(
                record,
                target=target,
                books_subdir=books_subdir,
                cache=cache,
                version=version,
                run_kepubify=run_kepubify,
                workspace=workspace_dir,
                report=report,
                catalog=catalog,
                device_id=device_id,
                now=now,
                on_stage=on_stage,
            )
    finally:
        if workspace_dir.exists():
            with contextlib.suppress(OSError):
                workspace_dir.rmdir()

    if status_push_enabled and device_id is not None and serial is not None:
        _push_read_state(
            catalog=catalog,
            device_id=device_id,
            target=target,
            serial=serial,
            backup_root=backup_root,
            report=report,
        )

    return report

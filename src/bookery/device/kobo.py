# ABOUTME: Kobo device sync — detects mounted readers and copies kepubs to them.
# ABOUTME: The library stays canonical EPUB; kepubify runs only inside this module.

import contextlib
import datetime as _dt
import getpass
import hashlib
import logging
import platform
import shutil
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from bookery.core.pathformat import sanitize_component
from bookery.db.hashing import compute_file_hash
from bookery.db.mapping import BookRecord
from bookery.db.status import PushCandidate
from bookery.device.kepub_cache import QuickCheckEntry
from bookery.device.kobo_backup import backup_kobo_db
from bookery.device.kobo_reader import pull_read_state, read_kobo_serial
from bookery.device.kobo_writer import (
    CollectionShelfUpdate,
    ReadStatusUpdate,
    delete_orphan_shelves,
    push_read_status,
    write_collection_shelves,
)

KOBO_MARKER = ".kobo"

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    # UTC to match SQLite's `strftime('%Y-%m-%dT%H:%M:%S', 'now')` used
    # elsewhere in the catalog — keeps merge timestamps comparable.
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0, tzinfo=None).isoformat()


def _now_kobo() -> str:
    # Kobo's own Shelf/ShelfContent rows use ISO-8601 UTC with a trailing 'Z'
    # (e.g. 2024-08-11T06:37:35Z). nickel expects that exact shape, so shelf
    # writes use this rather than the bare-naive form `_now_iso` produces.
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0, tzinfo=None).isoformat() + "Z"


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
    # Number of device_files rows the pre-pull discovery phase wrote (or
    # re-stamped) by matching catalog records against files already on the
    # mount. Surfaces the self-healing pass so users can see why a previously
    # quiet pull suddenly resolves a large cohort.
    device_files_discovered: int = 0
    # P2: device-side write counts. ``read_statuses_pushed`` is rows we
    # actually mutated on the Kobo; ``read_status_pull_only`` is push
    # candidates whose ContentID didn't match a current device row (book
    # copied this sync but not yet indexed by firmware); ``read_status_push_failed``
    # is (content_id, error_message) pairs from a rollback scenario.
    read_statuses_pushed: int = 0
    read_status_pull_only: int = 0
    read_status_push_failed: list[tuple[str, str]] = field(default_factory=list)
    # P2a: Collection shelf push stats (Slice 2). ``shelves_pushed`` is shelves
    # written this sync; unchanged shelves are skipped via member_hash and not
    # counted. ``shelves_skipped`` is (name, reason) pairs for shelves left alone
    # (e.g. a name collision with a user-created shelf). ``shelves_deleted`` is
    # the names of bookery-owned shelves removed because their collection is gone.
    shelves_pushed: int = 0
    shelf_push_failed: list[tuple[str, str]] = field(default_factory=list)
    shelves_skipped: list[tuple[str, str]] = field(default_factory=list)
    shelves_deleted: list[str] = field(default_factory=list)
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

    # Collection shelf methods (Slice 2)
    def upsert_device_shelf_state(
        self,
        *,
        device_id: int,
        collection_id: int,
        shelf_id: str,
        shelf_name: str,
        last_pushed_at: str,
        book_count_on_device: int | None = None,
        member_hash: str | None = None,
    ) -> None: ...

    def get_collection_shelf_state(
        self, device_id: int, collection_id: int
    ) -> dict[str, object] | None: ...

    def list_collection_shelf_candidates(self, *, device_id: int) -> list[dict[str, object]]: ...

    def list_collection_device_paths(self, *, collection_id: int, device_id: int) -> list[str]: ...


class _CacheProto(Protocol):
    def get(self, source_hash: str, kepubify_version: str) -> str | None: ...

    def put(
        self,
        source_hash: str,
        kepubify_version: str,
        kepub_sha: str,
        device_path: Path,
    ) -> None: ...

    def get_quickcheck(
        self, source_path: str, kepubify_version: str
    ) -> QuickCheckEntry | None: ...

    def record_quickcheck(
        self,
        *,
        source_path: str,
        kepubify_version: str,
        source_size: int,
        source_mtime: float,
        dest_path: str,
        dest_size: int,
        dest_mtime: float,
    ) -> None: ...


ProgressCallback = Callable[[int, int, BookRecord], None]
StageCallback = Callable[[str], None]


def _book_dest_dir(target: Path, books_subdir: str, record: BookRecord) -> Path:
    author_raw = record.metadata.authors[0] if record.metadata.authors else "Unknown Author"
    title_raw = record.metadata.title or "Untitled"
    author = sanitize_component(author_raw, fallback="Unknown Author")
    title = sanitize_component(title_raw, fallback="Untitled")
    return target / books_subdir / author / title


def _compute_device_dest(target: Path, books_subdir: str, record: BookRecord) -> Path:
    """Host-side path where the kepub for ``record`` would live on the mount.

    Pure function — does no I/O. Shared by the copy phase (which writes to this
    path) and the discovery phase (which checks whether it exists). Keeping the
    naming convention in one place prevents the two phases from drifting.
    """
    dest_dir = _book_dest_dir(target, books_subdir, record)
    title = sanitize_component(record.metadata.title, fallback="Untitled")
    return dest_dir / f"{title}.kepub.epub"


class _DiscoveryCatalogProto(Protocol):
    def upsert_device_file(
        self, *, device_id: int, book_id: int, remote_path: str, now: str
    ) -> None: ...


def discover_existing_device_files(
    catalog: _DiscoveryCatalogProto,
    *,
    records: list[BookRecord],
    target: Path,
    books_subdir: str,
    device_id: int,
    now: str,
) -> int:
    """Reconcile ``device_files`` against books already present on the mount.

    For each catalog record with an ``output_path``, compute the host-side
    path where the kepub would live (:func:`_compute_device_dest`) and, if a
    file is present there, upsert the corresponding ``device_files`` row.

    Runs before :func:`pull_read_state` so that books bookery copied in a
    prior session — or in this same session's cached path — are visible to
    ``resolve_book_id_for_remote_path``. Without this pass, a brand-new
    ``device_files`` schema (introduced in #180) sees only the books bookery
    has just full-converted, missing the long tail.

    Cost is one ``Path.exists()`` per record; sub-second for thousands of
    books. Returns the number of upserts performed.
    """
    discovered = 0
    for record in records:
        if record.output_path is None:
            continue
        dest = _compute_device_dest(target, books_subdir, record)
        if not dest.exists():
            continue
        catalog.upsert_device_file(
            device_id=device_id,
            book_id=record.id,
            remote_path=_to_device_path(dest, target),
            now=now,
        )
        discovered += 1
    return discovered


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
        report.skipped.append(
            (record.source_path or Path(f"book#{record.id}"), "no canonical EPUB in library")
        )
        return
    if source.suffix.lower() != ".epub":
        report.skipped.append((source, "output is not an EPUB"))
        return
    if not source.exists():
        report.failed.append((source, f"source missing: {source}"))
        return

    dest = _compute_device_dest(target, books_subdir, record)
    dest_dir = dest.parent

    def stamp_device_file() -> None:
        # Re-stamp device_files on every skip/copy path; otherwise books that
        # pre-date P1a (#180) — or any book that's been on the device long
        # enough to skip conversion — stay invisible to ``list_push_candidates``
        # and the read-status push silently no-ops (#188). Idempotent.
        if device_id is not None:
            catalog.upsert_device_file(
                device_id=device_id,
                book_id=record.id,
                remote_path=_to_device_path(dest, target),
                now=now,
            )

    def record_quickcheck() -> None:
        # Best-effort: a missing snapshot just costs a hash next sync.
        try:
            s = source.stat()
            d = dest.stat()
        except OSError:
            return
        cache.record_quickcheck(
            source_path=str(source),
            kepubify_version=version,
            source_size=s.st_size,
            source_mtime=s.st_mtime,
            dest_path=str(dest),
            dest_size=d.st_size,
            dest_mtime=d.st_mtime,
        )

    # Quick-skip: if size+mtime of both the source and the on-device file match
    # what we recorded last sync, nothing changed — skip both hashes (the dest
    # hash is a full read back over USB, the dominant resync cost). Any mismatch
    # falls through to the hash path below, which re-records the snapshot.
    qc = cache.get_quickcheck(str(source), version)
    if qc is not None and qc.dest_path == dest and dest.exists():
        try:
            s_stat = source.stat()
            d_stat = dest.stat()
        except OSError:
            s_stat = d_stat = None
        if (
            s_stat is not None
            and d_stat is not None
            and (s_stat.st_size, s_stat.st_mtime) == (qc.source_size, qc.source_mtime)
            and (d_stat.st_size, d_stat.st_mtime) == (qc.dest_size, qc.dest_mtime)
        ):
            stage("cached")
            report.skipped.append((dest, "already up to date"))
            stamp_device_file()
            return

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
                # Record the stat snapshot so the next sync quick-skips this
                # book without reading either file.
                record_quickcheck()
                stamp_device_file()
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
    record_quickcheck()
    stage("done")
    report.copied.append(dest)
    stamp_device_file()


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
        updates.append(ReadStatusUpdate(content_id=content_id, status=cand.catalog_status))
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
        logger.warning("KoboReader.sqlite not found at %s; skipping read-status push", db_path)
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
        report.read_status_push_failed = [(upd.content_id, str(exc)) for upd in updates]
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
                report.skipped.append(
                    (
                        record.source_path or Path(f"book#{record.id}"),
                        "no canonical EPUB in library",
                    )
                )
                continue
            if source.suffix.lower() != ".epub":
                report.skipped.append((source, "output is not an EPUB"))
                continue
            report.copied.append(_compute_device_dest(target, books_subdir, record))
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
        # Discovery runs *before* the pull so that books bookery copied in a
        # prior session — or that pre-date the `device_files` schema (#180) —
        # are resolvable by ContentID. Without this, the pull can only see
        # books bookery has just full-converted in this session, missing the
        # long tail (#190).
        try:
            report.device_files_discovered = discover_existing_device_files(
                catalog,
                records=records,
                target=target,
                books_subdir=books_subdir,
                device_id=device_id,
                now=now,
            )
        except Exception as exc:
            logger.warning("device_files discovery failed; continuing with pull: %s", exc)
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
        _push_collection_shelves(
            catalog=catalog,
            device_id=device_id,
            target=target,
            report=report,
        )

    return report


# Bump when the on-device shelf write format changes, to force a re-push that
# overwrites shelves left by an older format. v1 = phantom ContentList table
# (never rendered); v2 = real Shelf/ShelfContent, _IsSynced='true'; v3 =
# ShelfContent keyed on InternalName so nickel actually renders membership.
_SHELF_WRITE_FORMAT = "v3"


def _shelf_member_hash(shelf_name: str, content_ids: list[str]) -> str:
    """Digest of a shelf's pushed membership, for idempotent no-op detection.

    Order-independent over content (sorted) and sensitive to the shelf name so a
    rename also triggers a re-push. ``_SHELF_WRITE_FORMAT`` is mixed in so that
    changing how shelves are written to the device (e.g. the v1 phantom
    ``ContentList`` layout → v2 real ``Shelf``/``ShelfContent`` with
    ``_IsSynced='true'``) invalidates every stored hash and forces a one-time
    re-push that heals shelves written by an older, broken format.
    """
    payload = (
        _SHELF_WRITE_FORMAT + "\x00" + "\n".join(sorted(content_ids)) + "\x00" + shelf_name
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _push_collection_shelves(
    *,
    catalog: _CatalogProto,
    device_id: int,
    target: Path,
    report: SyncReport,
) -> None:
    """Push collection shelves to the device's Shelf/ShelfContent tables.

    For each collection with books on this device, builds the shelf membership
    from the catalog, skips the device write when the membership is unchanged
    (member_hash match), and writes the rest. Afterwards, bookery-owned shelves
    whose collection no longer maps here are removed. Persists shelf state
    (including the member_hash) back to the catalog.
    """
    try:
        candidates = catalog.list_collection_shelf_candidates(device_id=device_id)
    except Exception as exc:
        logger.warning("Could not list collection shelf candidates: %s", exc)
        return

    db_path = target / ".kobo" / "KoboReader.sqlite"
    if not db_path.exists():
        logger.warning(
            "KoboReader.sqlite not found at %s; skipping collection shelf push", db_path
        )
        return

    now = _now_iso()
    valid_internal_names: set[str] = set()
    updates: list[CollectionShelfUpdate] = []
    # Carry (collection_id, internal_name, member_hash, count) for shelves we write.
    pending_state: list[tuple[int, str, str, int]] = []

    for cand in candidates:
        collection_id: int = cand["collection_id"]  # type: ignore[assignment]
        name: str = cand["name"]  # type: ignore[assignment]
        internal_name = f"bookery-{collection_id}"
        valid_internal_names.add(internal_name)

        content_ids = _get_collection_content_ids(catalog, device_id, collection_id)
        member_hash = _shelf_member_hash(name, content_ids)

        existing_state = catalog.get_collection_shelf_state(device_id, collection_id)
        if existing_state is not None and existing_state.get("member_hash") == member_hash:
            # Unchanged since last push — skip the device write (idempotent no-op).
            continue

        shelf_id: str = (
            existing_state["shelf_id"]  # type: ignore[assignment]
            if existing_state is not None
            else str(uuid.uuid4())
        )
        updates.append(
            CollectionShelfUpdate(
                shelf_id=shelf_id,
                internal_name=internal_name,
                shelf_name=name,
                content_ids=content_ids,
            )
        )
        pending_state.append((collection_id, internal_name, member_hash, len(content_ids)))

    if updates:
        try:
            push_result = write_collection_shelves(
                db_path=db_path,
                updates=updates,
                now=_now_kobo,
            )
        except Exception as exc:
            logger.warning("Collection shelf push failed: %s", exc)
            report.shelf_push_failed = [(upd.shelf_name, str(exc)) for upd in updates]
            return

        report.shelves_pushed = push_result.pushed_count
        report.shelf_push_failed = list(push_result.failed)
        report.shelves_skipped = list(push_result.skipped)

        skipped_names = {name for name, _ in push_result.skipped}
        for upd, (collection_id, _internal, member_hash, count) in zip(
            updates, pending_state, strict=True
        ):
            if upd.shelf_name in skipped_names:
                continue
            catalog.upsert_device_shelf_state(
                device_id=device_id,
                collection_id=collection_id,
                shelf_id=upd.shelf_id,
                shelf_name=upd.shelf_name,
                last_pushed_at=now,
                book_count_on_device=count,
                member_hash=member_hash,
            )

    # Remove shelves we own whose collection no longer maps to this device.
    try:
        report.shelves_deleted = delete_orphan_shelves(
            db_path=db_path, valid_internal_names=valid_internal_names
        )
    except Exception as exc:
        logger.warning("Orphan shelf cleanup failed: %s", exc)


def _get_collection_content_ids(
    catalog: _CatalogProto,
    device_id: int,
    collection_id: int,
) -> list[str]:
    """Return Kobo ContentIDs for books in a collection that are on this device.

    Membership comes from the catalog (collection_books ∩ device_files), not the
    device DB. Each on-device remote path is turned into the ``file://`` ContentID
    the Kobo ``ShelfContent`` table uses, e.g.
    ``file:///mnt/onboard/Bookery/Author/Title/Title.kepub.epub``.
    """
    paths = catalog.list_collection_device_paths(collection_id=collection_id, device_id=device_id)
    return [f"file://{path}" for path in paths]

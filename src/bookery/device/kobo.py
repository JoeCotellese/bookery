# ABOUTME: Kobo device sync — detects mounted readers and copies kepubs to them.
# ABOUTME: The library stays canonical EPUB; kepubify runs only inside this module.

import contextlib
import getpass
import platform
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from bookery.core.pathformat import sanitize_component
from bookery.db.hashing import compute_file_hash
from bookery.db.mapping import BookRecord

KOBO_MARKER = ".kobo"


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


def detect_mounted_kobo(
    *, candidates: Iterable[Path] | None = None
) -> Path | None:
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


class _CatalogProto(Protocol):
    def list_all(self) -> list[BookRecord]: ...


class _CacheProto(Protocol):
    def get(self, source_hash: str, kepubify_version: str) -> str | None: ...

    def put(
        self,
        source_hash: str,
        kepubify_version: str,
        kepub_sha: str,
        device_path: Path,
    ) -> None: ...


def _book_dest_dir(target: Path, books_subdir: str, record: BookRecord) -> Path:
    author_raw = (
        record.metadata.authors[0] if record.metadata.authors else "Unknown Author"
    )
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
) -> None:
    source = record.output_path
    if source is None:
        report.skipped.append(
            (record.source_path, "no canonical EPUB in library")
        )
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

    try:
        source_hash = compute_file_hash(source)
    except OSError as exc:
        report.failed.append((source, f"hash failed: {exc}"))
        return

    cached_kepub_sha = cache.get(source_hash, version)
    if cached_kepub_sha is not None and dest.exists():
        try:
            if compute_file_hash(dest) == cached_kepub_sha:
                report.skipped.append((dest, "already up to date"))
                return
        except OSError:
            pass  # fall through to re-convert

    try:
        kepub_path = run_kepubify(source, out_dir=workspace)
    except Exception as exc:
        report.failed.append((source, f"kepubify error: {exc}"))
        return

    try:
        kepub_sha = compute_file_hash(kepub_path)
        dest_dir.mkdir(parents=True, exist_ok=True)
        # shutil.move handles cross-device renames and streams large files.
        shutil.move(str(kepub_path), str(dest))
    except OSError as exc:
        report.failed.append((source, f"copy failed: {exc}"))
        return

    cache.put(source_hash, version, kepub_sha, dest)
    report.copied.append(dest)


ProgressCallback = Callable[[int, int, BookRecord], None]


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
                    (record.source_path, "no canonical EPUB in library")
                )
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
            )
    finally:
        if workspace_dir.exists():
            with contextlib.suppress(OSError):
                workspace_dir.rmdir()

    return report

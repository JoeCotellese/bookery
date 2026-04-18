# ABOUTME: Kobo device sync — detects mounted readers and copies kepubs to them.
# ABOUTME: The library stays canonical EPUB; kepubify runs only inside this module.

import contextlib
import getpass
import hashlib
import platform
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from bookery.core.pathformat import sanitize_component
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


_HASH_CHUNK = 1024 * 1024


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


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
        self, source_hash: str, kepubify_version: str, kepub_sha: str
    ) -> None: ...


def _book_dest_dir(target: Path, books_subdir: str, record: BookRecord) -> Path:
    author_raw = (
        record.metadata.authors[0] if record.metadata.authors else "Unknown Author"
    )
    title_raw = record.metadata.title or "Untitled"
    author = sanitize_component(author_raw, fallback="Unknown Author")
    title = sanitize_component(title_raw, fallback="Untitled")
    return target / books_subdir / author / title


def sync_library_to_kobo(
    *,
    catalog: _CatalogProto,
    target: Path,
    cache: _CacheProto,
    run_kepubify: Callable[..., Path],
    kepubify_version: Callable[[], str],
    books_subdir: str = "Books",
    dry_run: bool = False,
) -> SyncReport:
    """Walk the catalog and mirror its EPUBs to a Kobo as .kepub.epub files.

    Cache semantics: row keyed on (source_sha256, kepubify_version) -> kepub_sha.
    On re-sync we hash the on-device file; if it matches the cached kepub_sha
    we skip kepubify entirely. Cache miss or device-file mismatch triggers a
    fresh kepubify run.

    Dependencies are injected so this function stays unit-testable; the CLI
    wires up the real KepubCache and the kepubify subprocess wrapper.
    """
    report = SyncReport()
    version = kepubify_version() if not dry_run else "dry-run"
    workspace = target.parent / ".bookery-sync-tmp"
    if not dry_run:
        workspace.mkdir(parents=True, exist_ok=True)

    for record in catalog.list_all():
        source = record.output_path
        if source is None:
            report.skipped.append(
                (record.source_path, "no canonical EPUB in library")
            )
            continue
        if source.suffix.lower() != ".epub":
            report.skipped.append((source, "output is not an EPUB"))
            continue
        if not source.exists():
            report.failed.append((source, f"source missing: {source}"))
            continue

        dest_dir = _book_dest_dir(target, books_subdir, record)
        title = sanitize_component(record.metadata.title, fallback="Untitled")
        dest = dest_dir / f"{title}.kepub.epub"

        if dry_run:
            report.copied.append(dest)
            continue

        try:
            source_hash = _hash_file(source)
        except OSError as exc:
            report.failed.append((source, f"hash failed: {exc}"))
            continue

        cached_kepub_sha = cache.get(source_hash, version)
        if cached_kepub_sha is not None and dest.exists():
            try:
                if _hash_file(dest) == cached_kepub_sha:
                    report.skipped.append((dest, "already up to date"))
                    continue
            except OSError:
                pass  # fall through to re-convert

        try:
            kepub_path = run_kepubify(source, out_dir=workspace)
        except Exception as exc:
            report.failed.append((source, f"kepubify error: {exc}"))
            continue

        try:
            kepub_sha = _hash_file(kepub_path)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(kepub_path.read_bytes())
            kepub_path.unlink(missing_ok=True)
        except OSError as exc:
            report.failed.append((source, f"copy failed: {exc}"))
            continue

        cache.put(source_hash, version, kepub_sha)
        report.copied.append(dest)

    if not dry_run and workspace.exists():
        with contextlib.suppress(OSError):
            workspace.rmdir()

    return report

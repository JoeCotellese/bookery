# ABOUTME: Pure removal logic for catalog rows and their on-disk files.
# ABOUTME: Owns sibling-file discovery, duplicate-cluster detection, and empty-dir cleanup.

from dataclasses import dataclass
from pathlib import Path

from bookery.db.catalog import LibraryCatalog


@dataclass(frozen=True)
class RemoveResult:
    """Outcome of a single ``remove_book`` invocation.

    ``file_path`` is the catalog's ``output_path`` (None if the row had no
    file recorded). ``file_removed`` is True only when we actually unlinked
    that primary file; missing-on-disk, --keep-file, and duplicate-cluster
    cases all leave it False and surface a warning instead.
    """

    book_id: int
    title: str
    author: str
    file_path: Path | None
    file_removed: bool
    siblings_removed: tuple[Path, ...]
    warnings: tuple[str, ...]


def _other_rows_pointing_at(catalog: LibraryCatalog, output_path: Path, exclude_id: int) -> int:
    """Count other catalog rows whose ``output_path`` matches ``output_path``.

    We compare on the stringified path the catalog stored — this is what
    ``add_book`` writes, so equality here mirrors the duplicate-cluster
    invariant exactly.
    """
    cursor = catalog._conn.execute(
        "SELECT COUNT(*) FROM books WHERE output_path = ? AND id != ?",
        (str(output_path), exclude_id),
    )
    return int(cursor.fetchone()[0])


def _discover_siblings(primary: Path) -> list[Path]:
    """Find files in the same directory that share the primary's stem.

    Example: for ``book.epub`` this returns ``book.kepub.epub`` (any file
    whose name starts with ``book.`` other than the primary itself).
    Symlinks are returned as-is; the caller is responsible for the
    "unlink only" semantics.
    """
    parent = primary.parent
    if not parent.is_dir():
        return []
    # ``Path.stem`` strips the final suffix only — for ``book.epub`` that's
    # ``book``. Sibling files like ``book.kepub.epub`` start with ``book.``.
    prefix = primary.stem + "."
    siblings: list[Path] = []
    for entry in parent.iterdir():
        if entry == primary:
            continue
        if not entry.is_file() and not entry.is_symlink():
            continue
        if entry.name.startswith(prefix):
            siblings.append(entry)
    return siblings


def _cleanup_empty_parents(library_path: Path, levels: int = 2) -> None:
    """Remove up to ``levels`` ancestor directories that became empty.

    For ``library_root/Author/Title/book.epub`` this prunes the Title and
    Author directories when they're empty after deletion. ``library_root``
    itself is implicitly safe because we stop after ``levels`` jumps.
    """
    parent = library_path.parent
    for _ in range(levels):
        try:
            # ``rmdir`` only succeeds on empty dirs — exactly the guard we
            # want, no need for a manual ``iterdir`` check first.
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent


def remove_book(
    catalog: LibraryCatalog,
    book_id: int,
    *,
    keep_file: bool,
) -> RemoveResult:
    """Delete one cataloged book and (optionally) its file(s) on disk.

    Operation order:

    1. Load the row. Raise ``ValueError`` if the ID is unknown.
    2. Decide whether the file is safe to delete (skip on --keep-file, on
       missing output_path, or when it's part of a duplicate cluster).
    3. Delete the DB row first — FK cascades clean up tags, genres, and
       provenance. If the SQL fails the file is untouched.
    4. Unlink the primary file and any siblings sharing its stem; treat
       already-missing as a soft warning. Prune empty parent directories.

    Symlinks: ``Path.unlink`` deletes the link only, leaving the target
    intact. The CLI ``--help`` documents this.

    Raises:
        ValueError: If ``book_id`` is not in the catalog.
    """
    record = catalog.get_by_id(book_id)
    if record is None:
        raise ValueError(f"Book with id {book_id} not found")

    title = record.metadata.title
    author = record.metadata.author or "Unknown"
    file_path = record.output_path

    warnings: list[str] = []
    skip_disk = keep_file

    # Duplicate-cluster check: if any other row also points at this exact
    # output_path, we must not unlink the shared file.
    if not skip_disk and file_path is not None:
        other_count = _other_rows_pointing_at(catalog, file_path, book_id)
        if other_count > 0:
            warnings.append(
                f"{other_count} other catalog entries point at this file; "
                f"keeping {file_path} on disk."
            )
            skip_disk = True

    # Commit the DB delete before touching the filesystem. If the SQL
    # raises, the file is still on disk and the user can retry safely.
    catalog.delete_book(book_id)

    file_removed = False
    siblings_removed: list[Path] = []

    if file_path is None:
        return RemoveResult(
            book_id=book_id,
            title=title,
            author=author,
            file_path=None,
            file_removed=False,
            siblings_removed=(),
            warnings=tuple(warnings),
        )

    if skip_disk:
        return RemoveResult(
            book_id=book_id,
            title=title,
            author=author,
            file_path=file_path,
            file_removed=False,
            siblings_removed=(),
            warnings=tuple(warnings),
        )

    siblings = _discover_siblings(file_path)

    # Primary file
    try:
        file_path.unlink()
        file_removed = True
    except FileNotFoundError:
        warnings.append(f"file already missing: {file_path}")
    except OSError as exc:
        warnings.append(f"could not delete {file_path}: {exc}")

    # Siblings
    for sibling in siblings:
        try:
            sibling.unlink()
            siblings_removed.append(sibling)
        except FileNotFoundError:
            warnings.append(f"sibling already missing: {sibling}")
        except OSError as exc:
            warnings.append(f"could not delete sibling {sibling}: {exc}")

    # Only attempt parent cleanup if we actually unlinked at least the
    # primary — otherwise leaving the dir alone is the safer call.
    if file_removed:
        _cleanup_empty_parents(file_path, levels=2)

    return RemoveResult(
        book_id=book_id,
        title=title,
        author=author,
        file_path=file_path,
        file_removed=file_removed,
        siblings_removed=tuple(siblings_removed),
        warnings=tuple(warnings),
    )

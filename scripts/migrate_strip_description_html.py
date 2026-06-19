#!/usr/bin/env python3
# ABOUTME: One-shot migration that strips HTML from existing book descriptions.
# ABOUTME: Idempotent — re-running on already-stripped rows is a no-op.

"""Clean the ``books.description`` column in-place.

The web UI stores plain text on write (see issue #123), but rows written
before the fix may carry HTML markup like ``<p class="description">…``
that renders as escaped literal text in the detail page and edit form.

Usage:
    uv run python scripts/migrate_strip_description_html.py PATH_TO_LIBRARY.db
    uv run python scripts/migrate_strip_description_html.py --dry-run PATH_TO_LIBRARY.db

The default run prints a count of rows touched. ``--dry-run`` prints the
same count and the first few affected ids without writing.

Idempotent: ``strip_html`` is a fixed point on plain text input, so a row
already cleaned does not register as a change on a second pass. Tested in
``tests/integration/test_strip_description_migration.py``.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Allow running the script straight from the repo without installing the
# package — prepend ``src/`` to sys.path so ``bookery.util.text`` imports.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from bookery.util.text import strip_html  # noqa: E402


def migrate(db_path: Path, *, dry_run: bool = False) -> int:
    """Strip HTML from every non-null description in the catalog.

    Returns the number of rows whose description value actually changed.
    A "changed" row is one where ``strip_html(value) != value``. Rows that
    are already plain text are left alone (the UPDATE is filtered, not
    blanket-applied, so we don't bump ``date_modified`` for no reason).
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("SELECT id, description FROM books WHERE description IS NOT NULL")
        updates: list[tuple[str, int]] = []
        for row in cursor:
            cleaned = strip_html(row["description"])
            if cleaned != row["description"]:
                updates.append((cleaned, row["id"]))

        if dry_run:
            preview = ", ".join(str(book_id) for _, book_id in updates[:10])
            print(f"[dry-run] would clean {len(updates)} description rows", flush=True)
            if preview:
                print(f"[dry-run] sample ids: {preview}", flush=True)
            return len(updates)

        if updates:
            conn.executemany(
                "UPDATE books SET description = ? WHERE id = ?",
                updates,
            )
            conn.commit()
        print(f"Cleaned {len(updates)} description rows", flush=True)
        return len(updates)
    finally:
        conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db_path", type=Path, help="Path to the bookery library.db")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.db_path.exists():
        print(f"error: no such file: {args.db_path}", file=sys.stderr)
        return 2
    migrate(args.db_path, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# ABOUTME: One-off migration that copies all cataloged books to the configured library_root.
# ABOUTME: Builds Author/Title layout, populates output_path, writes a reversible log file.

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from bookery.core.config import get_library_root
from bookery.core.pathformat import build_output_path
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library
from bookery.db.mapping import BookRecord


@dataclass
class PlannedAction:
    book_id: int
    title: str
    current: Path | None  # None = unrecoverable
    target: Path | None   # None = unrecoverable
    reason: str           # "ok" | "already-at-target" | "missing-source" | "missing-output"


def _resolve_current_location(record: BookRecord, legacy_cwd: Path) -> Path | None:
    """Find the on-disk location of a cataloged book.

    Prefers output_path if present. If it is relative, it's resolved against
    `legacy_cwd` (where old bookery runs wrote relative paths). Falls back to
    source_path. Returns None if nothing exists on disk.
    """
    if record.output_path is not None:
        candidate = record.output_path
        if not candidate.is_absolute():
            candidate = (legacy_cwd / candidate).resolve()
        if candidate.exists():
            return candidate
    source = record.source_path
    if source.exists():
        return source
    return None


def plan_actions(
    records: Iterable[BookRecord],
    library_root: Path,
    legacy_cwd: Path,
) -> list[PlannedAction]:
    """Compute the set of copy+DB-update operations without touching disk/DB."""
    actions: list[PlannedAction] = []
    claimed: set[Path] = set()  # reserve target paths within this plan

    for record in records:
        current = _resolve_current_location(record, legacy_cwd)
        if current is None:
            actions.append(
                PlannedAction(
                    book_id=record.id,
                    title=record.metadata.title,
                    current=None,
                    target=None,
                    reason="missing-source" if record.output_path is None else "missing-output",
                )
            )
            continue

        ideal_target = build_output_path(record.metadata, library_root)
        if current == ideal_target:
            target = ideal_target
            reason = "already-at-target"
        else:
            target = _reserve_unique(ideal_target, claimed)
            reason = "ok"
        claimed.add(target)
        actions.append(
            PlannedAction(
                book_id=record.id,
                title=record.metadata.title,
                current=current,
                target=target,
                reason=reason,
            )
        )

    return actions


def _reserve_unique(target: Path, claimed: set[Path]) -> Path:
    """Like resolve_collision, but also avoids targets reserved within this plan."""
    def taken(p: Path) -> bool:
        return p.exists() or p in claimed

    if not taken(target):
        return target

    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    for counter in range(1, 10_000):
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not taken(candidate):
            return candidate
    raise OSError(f"Could not find a non-colliding filename for {target}")


def execute_actions(
    actions: list[PlannedAction],
    catalog: LibraryCatalog,
    conn: sqlite3.Connection,
    log_file: Path,
) -> dict[str, int]:
    """Perform copies and DB updates. Append a tab-separated log entry per action."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    counts = {
        "ok": 0,
        "already-at-target": 0,
        "missing-source": 0,
        "missing-output": 0,
        "errors": 0,
    }

    with log_file.open("a", encoding="utf-8") as log:
        log.write(f"# migration started at {datetime.now().isoformat()}\n")

        for action in actions:
            if action.current is None or action.target is None:
                counts[action.reason] += 1
                log.write(
                    f"{action.book_id}\t{action.reason}\t-\t-\t{action.title}\n"
                )
                continue

            try:
                if action.reason != "already-at-target":
                    action.target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(action.current, action.target)

                catalog.set_output_path(action.book_id, action.target)
                conn.commit()
                counts[action.reason] += 1
                log.write(
                    f"{action.book_id}\t{action.reason}\t{action.current}\t{action.target}\t{action.title}\n"
                )
            except Exception as exc:
                counts["errors"] += 1
                log.write(
                    f"{action.book_id}\terror\t{action.current}\t{action.target}\t{exc}\n"
                )

    return counts


def _print_summary(actions: list[PlannedAction], library_root: Path) -> None:
    counts: dict[str, int] = {}
    for a in actions:
        counts[a.reason] = counts.get(a.reason, 0) + 1

    print(f"Library root: {library_root}")
    print(f"Total rows:   {len(actions)}")
    for reason, n in sorted(counts.items()):
        print(f"  {reason:20s} {n}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually copy files and update DB. Without this flag, dry-run only.",
    )
    parser.add_argument(
        "--db", type=Path, default=None,
        help=f"Database path (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--library-root", type=Path, default=None,
        help="Override library root (default: from config).",
    )
    parser.add_argument(
        "--legacy-cwd", type=Path, default=Path.home() / "git" / "bookery",
        help="Directory used to resolve legacy relative output_path values.",
    )
    parser.add_argument(
        "--log-file", type=Path, default=None,
        help="Migration log path (default: ~/.bookery/migrations/<timestamp>.log).",
    )
    parser.add_argument(
        "--sample", type=int, default=10,
        help="How many planned actions to print in dry-run (default 10).",
    )
    args = parser.parse_args(argv)

    library_root = args.library_root or get_library_root()
    library_root.mkdir(parents=True, exist_ok=True)

    conn = open_library(args.db or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)
    records = catalog.list_all()

    actions = plan_actions(records, library_root, args.legacy_cwd)

    _print_summary(actions, library_root)
    print()
    print(f"Sample of {min(args.sample, len(actions))} planned actions:")
    for a in actions[: args.sample]:
        print(f"  [{a.reason}] {a.current} -> {a.target}")

    if not args.execute:
        print("\nDry-run only. Re-run with --execute to apply.")
        return 0

    log_file = args.log_file or (
        Path.home() / ".bookery" / "migrations"
        / f"{datetime.now().strftime('%Y%m%dT%H%M%S')}.log"
    )
    print(f"\nExecuting. Log: {log_file}")
    counts = execute_actions(actions, catalog, conn, log_file)
    print("\nResults:")
    for reason, n in sorted(counts.items()):
        print(f"  {reason:20s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

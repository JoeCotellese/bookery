# ABOUTME: The `bookery authors` command group, incl. `fix-sort` file-as backfill.
# ABOUTME: Rewrites library EPUBs so devices sort authors by surname (issue #262).

import os
import shutil
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli.options import db_option, resolve_db_path
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.hashing import compute_file_hash
from bookery.db.mapping import BookRecord
from bookery.formats.epub import (
    EpubReadError,
    creator_file_as_pairs,
    read_creator_file_as,
    read_epub_metadata,
    write_epub_metadata,
)

console = Console()


@dataclass
class _Candidate:
    """A cataloged book whose written file-as does not match the expected sort."""

    record: BookRecord
    current: list[tuple[str, str | None]]
    expected: list[tuple[str, str]]


def _find_candidates(catalog: LibraryCatalog) -> list[_Candidate]:
    """Return books whose library EPUB lacks the correct per-author file-as."""
    candidates: list[_Candidate] = []
    for record in catalog.list_all():
        out = record.output_path
        if out is None or out.suffix.lower() != ".epub" or not out.exists():
            continue
        if not record.metadata.authors:
            continue
        expected = creator_file_as_pairs(record.metadata)
        try:
            current = read_creator_file_as(out)
        except (OSError, zipfile.BadZipFile, ET.ParseError):
            continue
        if current != expected:
            candidates.append(_Candidate(record, current, expected))
    return candidates


def _apply_fix(catalog: LibraryCatalog, candidate: _Candidate) -> bool:
    """Rewrite one library EPUB atomically; return False if read-back verify fails.

    Writes to a sibling temp file, verifies the authors round-trip, then
    ``os.replace`` swaps it in (atomic on the same filesystem). A failed verify
    leaves the original untouched. The new file_hash is persisted so ``verify``
    doesn't later flag the rewritten copy as changed.
    """
    src = candidate.record.output_path
    assert src is not None  # guaranteed by _find_candidates
    tmp = src.with_name(src.name + ".fixtmp")
    shutil.copy2(src, tmp)
    try:
        write_epub_metadata(tmp, candidate.record.metadata)
        if read_epub_metadata(tmp).authors != candidate.record.metadata.authors:
            tmp.unlink(missing_ok=True)
            return False
        os.replace(tmp, src)
    except (OSError, EpubReadError):
        tmp.unlink(missing_ok=True)
        raise
    catalog.update_book(candidate.record.id, file_hash=compute_file_hash(src))
    return True


def _render_table(candidates: list[_Candidate]) -> Table:
    """Build the preview table: which authors change file-as, per book."""
    table = Table(title="Author file-as fixes")
    table.add_column("ID", style="dim", width=6, justify="right")
    table.add_column("Title")
    table.add_column("Author")
    table.add_column("file-as: now → fixed")
    for cand in candidates:
        current_by_name = dict(cand.current)
        for i, (author, expected_fa) in enumerate(cand.expected):
            now = current_by_name.get(author)
            table.add_row(
                str(cand.record.id) if i == 0 else "",
                cand.record.metadata.title if i == 0 else "",
                author,
                f"{now or '(none)'} → {expected_fa}",
            )
    return table


@click.group("authors")
def authors() -> None:
    """Manage author metadata across the library."""


@authors.command("fix-sort")
@db_option
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    default=False,
    help="Rewrite files. Without it, fix-sort only previews (dry run).",
)
def fix_sort(db_path: Path | None, apply_changes: bool) -> None:
    """Backfill opf:file-as so devices sort authors by surname.

    Library EPUBs written before this fix carry no file-as, so Kobo and others
    file authors by their given name. This rewrites each affected copy with a
    surname-first file-as. Dry-run by default; pass --apply to write.
    """
    conn = open_library(resolve_db_path(db_path))
    try:
        catalog = LibraryCatalog(conn)
        candidates = _find_candidates(catalog)

        if not candidates:
            console.print(
                "[green]All author file-as sort keys are already correct.[/green]"
            )
            return

        if not apply_changes:
            console.print(_render_table(candidates))
            console.print(
                f"\n[dim]dry-run:[/dim] {len(candidates)} book(s) would be updated. "
                "Re-run with --apply to write."
            )
            return

        fixed = 0
        for cand in candidates:
            if _apply_fix(catalog, cand):
                fixed += 1
            else:
                console.print(
                    f"[yellow]skipped (verify failed):[/yellow] "
                    f"{cand.record.metadata.title}"
                )
        console.print(f"[green]Updated file-as for {fixed} book(s).[/green]")
    finally:
        conn.close()

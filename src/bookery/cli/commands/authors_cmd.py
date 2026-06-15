# ABOUTME: The `bookery authors` command group, incl. `fix-sort` file-as backfill.
# ABOUTME: Rewrites library EPUBs so devices sort authors by surname (issue #262).

import os
import shutil
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import datetime
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
from bookery.metadata.author_names import canonical_author, classify

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
            try:
                applied = _apply_fix(catalog, cand)
            except (OSError, EpubReadError) as exc:
                # One unreadable file shouldn't abort the whole backfill; each
                # fix is atomic, so already-processed books stay valid.
                console.print(
                    f"[red]failed:[/red] {cand.record.metadata.title}: {exc}"
                )
                continue
            if applied:
                fixed += 1
            else:
                console.print(
                    f"[yellow]skipped (verify failed):[/yellow] "
                    f"{cand.record.metadata.title}"
                )
        console.print(f"[green]Updated file-as for {fixed} book(s).[/green]")
    finally:
        conn.close()


def _backup_db(db_path: Path) -> Path:
    """Copy the DB to a timestamped sibling and print a restore command."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = db_path.with_name(f"{db_path.name}.bak-{ts}")
    shutil.copy2(db_path, backup)
    console.print(f"[dim]Backed up database to[/dim] {backup}")
    console.print(f'[dim]Restore with:[/dim] cp "{backup}" "{db_path}"')
    return backup


@authors.command("list")
@db_option
@click.option(
    "--duplicates",
    "duplicates_only",
    is_flag=True,
    default=False,
    help="Show only authors stored under more than one spelling.",
)
def list_authors(db_path: Path | None, duplicates_only: bool) -> None:
    """List authors and their book counts (or only duplicate spellings)."""
    conn = open_library(resolve_db_path(db_path))
    try:
        catalog = LibraryCatalog(conn)
        if duplicates_only:
            clusters = catalog.author_clusters()
            if not clusters:
                console.print("[green]No duplicate author spellings found.[/green]")
                return
            table = Table(title="Duplicate authors")
            table.add_column("Spelling")
            table.add_column("Books", justify="right")
            for cluster in clusters:
                for form in cluster.forms:
                    table.add_row(form.name, str(len(form.book_ids)))
                table.add_section()
            console.print(table)
            return

        forms = catalog.author_forms()
        if not forms:
            console.print("[yellow]No authors in the catalog.[/yellow]")
            return
        table = Table(title="Authors")
        table.add_column("Author")
        table.add_column("Books", justify="right")
        for name in sorted(forms, key=str.lower):
            table.add_row(name, str(len(forms[name])))
        console.print(table)
    finally:
        conn.close()


@authors.command("normalize")
@db_option
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    default=False,
    help="Write the rewrites. Without it, normalize only previews (dry run).",
)
@click.option(
    "--include-reversed",
    "include_reversed",
    is_flag=True,
    default=False,
    help="Also flip reversed names with no existing twin (lower confidence).",
)
def normalize(
    db_path: Path | None, apply_changes: bool, include_reversed: bool
) -> None:
    """Reorder ``Surname, Given`` author names to ``Given Surname``.

    Dry-run by default. The default tier touches only collision-confirmed
    names — where the flipped spelling already exists elsewhere in the catalog.
    Pass --include-reversed to also flip confidently-reorderable names that have
    no twin yet. Blob and credential forms are never auto-rewritten. --apply
    backs the database up first and prints a restore command.
    """
    db = resolve_db_path(db_path)
    conn = open_library(db)
    try:
        catalog = LibraryCatalog(conn)
        forms = catalog.author_forms()
        existing = set(forms)
        plan: list[tuple[str, str, int, bool]] = []
        for name in sorted(forms):
            if classify(name) != "reorderable":
                continue
            new = canonical_author(name)
            if new == name:
                continue
            confirmed = new in existing
            if confirmed or include_reversed:
                plan.append((name, new, len(forms[name]), confirmed))

        if not plan:
            console.print("[green]No author names need normalizing.[/green]")
            return

        table = Table(title="Author normalizations")
        table.add_column("now → normalized")
        table.add_column("Books", justify="right")
        table.add_column("Tier")
        for old, new, n_books, confirmed in plan:
            table.add_row(
                f"{old} → {new}",
                str(n_books),
                "collision-confirmed" if confirmed else "reversed",
            )
        console.print(table)

        if not apply_changes:
            console.print(
                f"\n[dim]dry-run:[/dim] {len(plan)} rewrite(s). "
                "Re-run with --apply to write."
            )
            return

        _backup_db(db)
        total = 0
        for old, new, _n, _c in plan:
            total += catalog.rewrite_author(old, new)
        console.print(
            f"[green]Normalized {len(plan)} name(s) across {total} book(s).[/green]"
        )
    finally:
        conn.close()


@authors.command("merge")
@db_option
@click.argument("forms", nargs=-1, required=True)
@click.option(
    "--into",
    "canonical",
    default=None,
    help="Canonical spelling to merge into. Prompts if omitted.",
)
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    default=False,
    help="Write the merge. Without it, merge only previews (dry run).",
)
def merge(
    db_path: Path | None,
    forms: tuple[str, ...],
    canonical: str | None,
    apply_changes: bool,
) -> None:
    """Merge arbitrary author spellings into one canonical form.

    For the cases ``normalize`` won't touch — typos, nicknames, credential
    tails. Pass the spellings as arguments and a canonical form via --into
    (or pick one interactively). Dry-run by default; --apply backs the database
    up first and prints a restore command.
    """
    db = resolve_db_path(db_path)
    conn = open_library(db)
    try:
        catalog = LibraryCatalog(conn)
        if canonical is None:
            for i, form in enumerate(forms, 1):
                console.print(f"  {i}. {form}")
            idx = click.prompt(
                "Which spelling is canonical?",
                type=click.IntRange(1, len(forms)),
            )
            canonical = forms[idx - 1]
        assert canonical is not None  # set above or supplied via --into

        sources = [form for form in forms if form != canonical]
        if not sources:
            console.print(
                "[yellow]Nothing to merge — every form equals the canonical.[/yellow]"
            )
            return

        table = Table(title="Author merge")
        table.add_column("from")
        table.add_column("into")
        for source in sources:
            table.add_row(source, canonical)
        console.print(table)

        if not apply_changes:
            console.print(
                f"\n[dim]dry-run:[/dim] would merge {len(sources)} spelling(s). "
                "Re-run with --apply to write."
            )
            return

        _backup_db(db)
        total = 0
        for source in sources:
            total += catalog.rewrite_author(source, canonical)
        console.print(
            f"[green]Merged {len(sources)} spelling(s) across {total} book(s).[/green]"
        )
    finally:
        conn.close()

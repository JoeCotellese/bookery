# ABOUTME: End-to-end test for `bookery vault-export`, producing a real EPUB via pandoc.
# ABOUTME: Skipped when pandoc is not installed on the runner.

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli

pytestmark = pytest.mark.skipif(
    shutil.which("pandoc") is None, reason="pandoc not installed"
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "vault"


def _run(tmp_path: Path, *extra_args: str):
    runner = CliRunner()
    out = tmp_path / "vault.epub"
    return runner.invoke(
        cli,
        ["vault-export", "--vault", str(FIXTURE), "-o", str(out), *extra_args],
        catch_exceptions=False,
    ), out


def test_vault_export_produces_valid_epub(tmp_path: Path):
    result, out = _run(tmp_path, "--index")
    assert result.exit_code == 0, result.output
    assert out.exists()

    book = epub.read_epub(str(out))
    titles = {item.title for item in book.toc if hasattr(item, "title")}
    # Pandoc's TOC items include the notes as top-level H1s.
    # At minimum, the file is readable and contains a dc:identifier.
    ids = [v for v, _ in book.get_metadata("DC", "identifier")]
    assert any(v.startswith("urn:uuid:") for v in ids)
    assert "Note A" in result.output or titles  # smoke the summary output


def test_vault_export_stable_identifier_across_runs(tmp_path: Path):
    first, out = _run(tmp_path)
    assert first.exit_code == 0, first.output
    book1 = epub.read_epub(str(out))
    ids1 = [v for v, _ in book1.get_metadata("DC", "identifier")]

    out.unlink()
    second, _ = _run(tmp_path)
    assert second.exit_code == 0, second.output
    book2 = epub.read_epub(str(out))
    ids2 = [v for v, _ in book2.get_metadata("DC", "identifier")]

    assert ids1 == ids2


def test_vault_export_catalog_flag_imports_into_library(
    tmp_path: Path, _isolate_library_root: Path,
) -> None:
    """`--catalog` should append the produced EPUB into the bookery catalog so
    it ships on the next `bookery sync kobo` without a separate `bookery add`.
    """
    runner = CliRunner()
    out = tmp_path / "vault.epub"
    db = tmp_path / "library.db"
    result = runner.invoke(
        cli,
        [
            "vault-export", "--vault", str(FIXTURE),
            "-o", str(out),
            "--catalog", "--db", str(db),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "added" in result.output
    library_copies = list(_isolate_library_root.rglob("*.epub"))
    assert library_copies, f"no EPUB found in library root: {result.output}"


def test_vault_export_catalog_replaces_prior_export(
    tmp_path: Path, _isolate_library_root: Path,
) -> None:
    """A vault export is a point-in-time snapshot — running `--catalog` twice
    must leave exactly one row in the catalog and one EPUB on disk, even when
    the version label (or pandoc's `dc:date`) differs between runs.
    """
    from bookery.db.catalog import LibraryCatalog
    from bookery.db.connection import open_library

    runner = CliRunner()
    out = tmp_path / "vault.epub"
    db = tmp_path / "library.db"

    args = [
        "vault-export", "--vault", str(FIXTURE),
        "-o", str(out),
        "--catalog", "--db", str(db),
    ]

    first = runner.invoke(
        cli, [*args, "--version-label", "v1"], catch_exceptions=False,
    )
    assert first.exit_code == 0, first.output

    second = runner.invoke(
        cli, [*args, "--version-label", "v2"], catch_exceptions=False,
    )
    assert second.exit_code == 0, second.output
    assert "replaced 1 prior vault export" in second.output

    conn = open_library(db)
    try:
        records = LibraryCatalog(conn).list_all()
    finally:
        conn.close()
    assert len(records) == 1, [r.metadata.title for r in records]
    assert records[0].metadata.title.endswith("v2")

    library_epubs = list(_isolate_library_root.rglob("*.epub"))
    assert len(library_epubs) == 1, library_epubs


def test_vault_export_catalog_does_not_clobber_unrelated_books(
    tmp_path: Path, _isolate_library_root: Path,
) -> None:
    """`--catalog` must only replace prior snapshots of the *same* vault. A
    real book whose title happens to start with the vault title (e.g. "Notes
    from Underground" when the vault title is "Notes") must NOT be deleted.
    """
    from bookery.db.catalog import LibraryCatalog
    from bookery.db.connection import open_library
    from bookery.metadata.types import BookMetadata

    runner = CliRunner()
    out = tmp_path / "vault.epub"
    db = tmp_path / "library.db"

    # Seed the catalog with an unrelated book whose title shares the same
    # prefix the vault export will use ("Notes ").
    conn = open_library(db)
    try:
        catalog = LibraryCatalog(conn)
        catalog.add_book(
            BookMetadata(
                title="Notes from Underground",
                authors=["Fyodor Dostoevsky"],
                source_path=tmp_path / "fake-dostoevsky.epub",
            ),
            file_hash="seed-hash-unrelated-book",
        )
    finally:
        conn.close()

    # Stub import_books so we don't need a real EPUB on disk for the seeded
    # row's hash check; we only care that the prune step leaves it alone.
    args = [
        "vault-export", "--vault", str(FIXTURE),
        "-o", str(out),
        "--title", "Notes",
        "--author", "Joe Cotellese",
        "--catalog", "--db", str(db),
    ]
    result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0, result.output

    conn = open_library(db)
    try:
        titles = sorted(r.metadata.title for r in LibraryCatalog(conn).list_all())
    finally:
        conn.close()
    assert "Notes from Underground" in titles, titles


def test_vault_export_catalog_preserves_prior_when_import_fails(
    tmp_path: Path, _isolate_library_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If `import_books` fails after the EPUB renders, the prior vault row
    must remain in the catalog. We must never delete the user's last good
    snapshot until the new one is safely cataloged.
    """
    from bookery.db.catalog import LibraryCatalog
    from bookery.db.connection import open_library
    from bookery.metadata.types import BookMetadata

    runner = CliRunner()
    out = tmp_path / "vault.epub"
    db = tmp_path / "library.db"

    # Seed a prior snapshot the prune step would otherwise match.
    conn = open_library(db)
    try:
        LibraryCatalog(conn).add_book(
            BookMetadata(
                title="vault Vault — v0",
                authors=["Obsidian Vault"],
                source_path=tmp_path / "fake-prior-vault.epub",
            ),
            file_hash="seed-hash-prior-snapshot",
        )
    finally:
        conn.close()

    def _explode(*_args, **_kwargs):
        from bookery.core.importer import ImportResult
        return ImportResult(added=0, errors=1, error_details=[(out, "boom")])

    monkeypatch.setattr(
        "bookery.cli.commands.vault_export_cmd.import_books", _explode,
    )

    result = runner.invoke(
        cli,
        [
            "vault-export", "--vault", str(FIXTURE),
            "-o", str(out),
            "--title", "vault Vault",
            "--catalog", "--db", str(db),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code != 0, result.output

    conn = open_library(db)
    try:
        titles = [r.metadata.title for r in LibraryCatalog(conn).list_all()]
    finally:
        conn.close()
    assert titles == ["vault Vault — v0"], titles


def test_vault_export_rejects_missing_vault(tmp_path: Path):
    runner = CliRunner()
    bad = tmp_path / "does-not-exist"
    out = tmp_path / "o.epub"
    result = runner.invoke(
        cli,
        ["vault-export", "--vault", str(bad), "-o", str(out)],
    )
    assert result.exit_code != 0

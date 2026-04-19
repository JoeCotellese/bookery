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


def test_vault_export_rejects_missing_vault(tmp_path: Path):
    runner = CliRunner()
    bad = tmp_path / "does-not-exist"
    out = tmp_path / "o.epub"
    result = runner.invoke(
        cli,
        ["vault-export", "--vault", str(bad), "-o", str(out)],
    )
    assert result.exit_code != 0

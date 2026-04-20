# ABOUTME: Verifies --no-cache on match/rematch disables the metadata response cache.
# ABOUTME: Ensures the CLI flag is wired through to the provider factory.

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from bookery.cli.commands.match_cmd import match
from bookery.cli.commands.rematch_cmd import rematch


def test_match_passes_use_cache_true_by_default(tmp_path: Path) -> None:
    epub = tmp_path / "stub.epub"
    epub.write_bytes(b"stub")
    out = tmp_path / "out"
    out.mkdir()

    with patch("bookery.cli.commands.match_cmd._create_provider") as factory:
        factory.return_value = MagicMock(lookup_by_url=lambda _: None)
        CliRunner().invoke(
            match,
            [str(epub), "-o", str(out), "-q", "--no-resume"],
            catch_exceptions=False,
        )
    factory.assert_called_once_with(use_cache=True)


def test_match_no_cache_flag_disables_cache(tmp_path: Path) -> None:
    epub = tmp_path / "stub.epub"
    epub.write_bytes(b"stub")
    out = tmp_path / "out"
    out.mkdir()

    with patch("bookery.cli.commands.match_cmd._create_provider") as factory:
        factory.return_value = MagicMock(lookup_by_url=lambda _: None)
        CliRunner().invoke(
            match,
            [str(epub), "-o", str(out), "-q", "--no-resume", "--no-cache"],
            catch_exceptions=False,
        )
    factory.assert_called_once_with(use_cache=False)


def test_rematch_no_cache_flag_disables_cache(tmp_path: Path) -> None:
    # rematch requires a DB + at least one book. The factory is short-circuited
    # by --all with no books in the catalog, so we just need the command to
    # reach the provider-construction branch.
    db = tmp_path / "lib.db"
    from bookery.db.catalog import LibraryCatalog
    from bookery.db.connection import open_library
    from bookery.metadata.types import BookMetadata

    conn = open_library(db)
    catalog = LibraryCatalog(conn)
    catalog.add_book(
        BookMetadata(title="T", authors=["A"], source_path=Path("/tmp/x.epub")),
        file_hash="h" * 64,
    )
    conn.close()

    with patch("bookery.cli.commands.rematch_cmd._create_provider") as factory:
        factory.return_value = MagicMock(lookup_by_url=lambda _: None)
        result = CliRunner().invoke(
            rematch,
            ["--all", "--db", str(db), "-q", "--no-resume", "--no-cache"],
            catch_exceptions=False,
        )
    assert factory.call_args.kwargs == {"use_cache": False}, result.output

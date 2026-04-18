# ABOUTME: Integration test for the Kobo sync pipeline (catalog + cache + kepubify stub).
# ABOUTME: Drives the real LibraryCatalog and KepubCache; only the subprocess is faked.

import subprocess
from pathlib import Path
from unittest.mock import patch

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.device.kepub_cache import KepubCache
from bookery.device.kepubify import kepubify_version, run_kepubify
from bookery.device.kobo import sync_library_to_kobo
from bookery.metadata.types import BookMetadata


def _fake_subprocess(cmd, **_kwargs):
    if "--version" in cmd:
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="kepubify v4.4.0\n", stderr=""
        )
    out = Path(cmd[cmd.index("-o") + 1])
    epub = Path(cmd[-1])
    out.parent.mkdir(parents=True, exist_ok=True)
    # Make payload deterministic-but-source-dependent so cache lookups behave.
    out.write_bytes(b"KEPUB:" + epub.read_bytes())
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


def _seed(library: Path, db_path: Path, *, n: int) -> None:
    conn = open_library(db_path)
    try:
        catalog = LibraryCatalog(conn)
        for i in range(n):
            epub = library / f"Author {i}" / f"Title {i}" / f"Title {i}.epub"
            epub.parent.mkdir(parents=True, exist_ok=True)
            epub.write_bytes(f"EPUB-{i}".encode())
            catalog.add_book(
                BookMetadata(
                    title=f"Title {i}",
                    authors=[f"Author {i}"],
                    source_path=epub,
                ),
                file_hash=f"hash-{i}",
                output_path=epub,
            )
    finally:
        conn.close()


def test_two_pass_sync_uses_cache(tmp_path: Path) -> None:
    library = tmp_path / "library"
    db_path = tmp_path / "lib.db"
    target = tmp_path / "kobo"
    target.mkdir()
    (target / ".kobo").mkdir()
    cache = KepubCache(tmp_path / "data" / "kepub_cache.db")

    _seed(library, db_path, n=2)

    with (
        patch("bookery.device.kepubify.shutil.which", return_value="/usr/bin/kepubify"),
        patch(
            "bookery.device.kepubify.subprocess.run", side_effect=_fake_subprocess
        ) as mock_run,
    ):
        conn = open_library(db_path)
        try:
            catalog = LibraryCatalog(conn)
            first = sync_library_to_kobo(
                catalog=catalog,
                target=target,
                cache=cache,
                run_kepubify=run_kepubify,
                kepubify_version=kepubify_version,
                workspace_dir=tmp_path / "workspace",
                books_subdir="Books",
            )
        finally:
            conn.close()

        assert len(first.copied) == 2
        assert len(first.skipped) == 0
        # 2 conversions + 1 version probe (cached for the rest of this call).
        first_call_count = mock_run.call_count
        assert first_call_count >= 3

        conn = open_library(db_path)
        try:
            catalog = LibraryCatalog(conn)
            second = sync_library_to_kobo(
                catalog=catalog,
                target=target,
                cache=cache,
                run_kepubify=run_kepubify,
                kepubify_version=kepubify_version,
                workspace_dir=tmp_path / "workspace",
                books_subdir="Books",
            )
        finally:
            conn.close()

        assert len(second.copied) == 0
        assert len(second.skipped) == 2
        # Only the version probe runs on second pass (one extra call).
        assert mock_run.call_count == first_call_count + 1


def test_missing_device_file_recopied(tmp_path: Path) -> None:
    library = tmp_path / "library"
    db_path = tmp_path / "lib.db"
    target = tmp_path / "kobo"
    target.mkdir()
    (target / ".kobo").mkdir()
    cache = KepubCache(tmp_path / "data" / "kepub_cache.db")
    _seed(library, db_path, n=2)

    with (
        patch("bookery.device.kepubify.shutil.which", return_value="/usr/bin/kepubify"),
        patch("bookery.device.kepubify.subprocess.run", side_effect=_fake_subprocess),
    ):
        conn = open_library(db_path)
        try:
            catalog = LibraryCatalog(conn)
            first = sync_library_to_kobo(
                catalog=catalog,
                target=target,
                cache=cache,
                run_kepubify=run_kepubify,
                kepubify_version=kepubify_version,
                workspace_dir=tmp_path / "workspace",
                books_subdir="Books",
            )
        finally:
            conn.close()

        # Delete one device file before the second sync.
        first.copied[0].unlink()

        conn = open_library(db_path)
        try:
            catalog = LibraryCatalog(conn)
            second = sync_library_to_kobo(
                catalog=catalog,
                target=target,
                cache=cache,
                run_kepubify=run_kepubify,
                kepubify_version=kepubify_version,
                workspace_dir=tmp_path / "workspace",
                books_subdir="Books",
            )
        finally:
            conn.close()

        assert len(second.copied) == 1
        assert len(second.skipped) == 1
        assert first.copied[0].exists()

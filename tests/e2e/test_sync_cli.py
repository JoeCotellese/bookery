# ABOUTME: End-to-end tests for the `bookery sync kobo` CLI command.
# ABOUTME: Drives the Click app with a real DB; stubs the kepubify subprocess.

import subprocess
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


def _seed(db_path: Path, library: Path) -> Path:
    epub = library / "Some Author" / "Some Title" / "Some Title.epub"
    epub.parent.mkdir(parents=True, exist_ok=True)
    epub.write_bytes(b"FAKE-EPUB")
    conn = open_library(db_path)
    try:
        catalog = LibraryCatalog(conn)
        catalog.add_book(
            BookMetadata(
                title="Some Title",
                authors=["Some Author"],
                source_path=epub,
            ),
            file_hash="seed-hash",
            output_path=epub,
        )
    finally:
        conn.close()
    return epub


def _make_kobo_root(tmp_path: Path) -> Path:
    root = tmp_path / "kobo"
    root.mkdir()
    (root / ".kobo").mkdir()
    return root


def _fake_kepubify(returncode: int = 0, stderr: str = "", payload: bytes = b"FAKE-KEPUB"):
    def runner(cmd, **_kwargs):
        if "--version" in cmd:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="kepubify v4.4.0\n", stderr=""
            )
        # `kepubify -o <out_path> <epub>` form (we pass the full filename).
        out = Path(cmd[cmd.index("-o") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        if returncode == 0:
            out.write_bytes(payload)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        raise subprocess.CalledProcessError(returncode, cmd, stderr=stderr)

    return runner


def test_empty_catalog_exits_zero(tmp_path: Path) -> None:
    db_path = tmp_path / "lib.db"
    open_library(db_path).close()
    target = _make_kobo_root(tmp_path)

    runner = CliRunner()
    with (
        patch("bookery.device.kepubify.shutil.which", return_value="/usr/bin/kepubify"),
        patch("bookery.device.kepubify.subprocess.run", side_effect=_fake_kepubify()),
    ):
        result = runner.invoke(
            cli,
            [
                "sync", "kobo",
                "--target", str(target),
                "--db", str(db_path),
                "--data-dir", str(tmp_path / "data"),
            ],
        )

    assert result.exit_code == 0, result.output
    assert "No books" in result.output or "0" in result.output


def test_sync_copies_kepub_to_target(tmp_path: Path) -> None:
    db_path = tmp_path / "lib.db"
    library = tmp_path / "library"
    _seed(db_path, library)
    target = _make_kobo_root(tmp_path)

    runner = CliRunner()
    with (
        patch("bookery.device.kepubify.shutil.which", return_value="/usr/bin/kepubify"),
        patch("bookery.device.kepubify.subprocess.run", side_effect=_fake_kepubify()),
    ):
        result = runner.invoke(
            cli,
            [
                "sync", "kobo",
                "--target", str(target),
                "--db", str(db_path),
                "--data-dir", str(tmp_path / "data"),
            ],
        )

    assert result.exit_code == 0, result.output
    expected = (
        target / "Bookery" / "Some Author" / "Some Title" / "Some Title.kepub.epub"
    )
    assert expected.exists()
    assert "Some Title" in result.output


def test_dry_run_makes_no_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "lib.db"
    library = tmp_path / "library"
    _seed(db_path, library)
    target = _make_kobo_root(tmp_path)

    runner = CliRunner()
    with (
        patch("bookery.device.kepubify.shutil.which", return_value="/usr/bin/kepubify"),
        patch("bookery.device.kepubify.subprocess.run", side_effect=_fake_kepubify()) as mock_run,
    ):
        result = runner.invoke(
            cli,
            [
                "sync", "kobo",
                "--target", str(target),
                "--dry-run",
                "--db", str(db_path),
                "--data-dir", str(tmp_path / "data"),
            ],
        )

    assert result.exit_code == 0, result.output
    # In dry-run we shouldn't call kepubify (not even --version).
    assert mock_run.call_count == 0
    # No kepub written.
    assert not list(target.rglob("*.kepub.epub"))


def test_kepubify_missing_exits_3(tmp_path: Path) -> None:
    db_path = tmp_path / "lib.db"
    library = tmp_path / "library"
    _seed(db_path, library)
    target = _make_kobo_root(tmp_path)

    runner = CliRunner()
    with patch("bookery.device.kepubify.shutil.which", return_value=None):
        result = runner.invoke(
            cli,
            [
                "sync", "kobo",
                "--target", str(target),
                "--db", str(db_path),
                "--data-dir", str(tmp_path / "data"),
            ],
        )

    assert result.exit_code == 3, result.output
    assert "kepubify" in result.output.lower()


def test_no_target_and_no_detection_fails(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "lib.db"
    open_library(db_path).close()
    monkeypatch.setattr("bookery.device.kobo._default_mount_roots", lambda: [])

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "sync", "kobo",
            "--db", str(db_path),
            "--data-dir", str(tmp_path / "data"),
        ],
    )

    assert result.exit_code == 1, result.output
    assert "kobo" in result.output.lower()

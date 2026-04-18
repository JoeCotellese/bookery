# ABOUTME: Unit tests for the copy_file helper in core.filecopy.
# ABOUTME: Covers content copy, mtime preservation, and PermissionError fallback.

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from bookery.core.filecopy import copy_file


def test_copy_file_copies_content(tmp_path: Path) -> None:
    source = tmp_path / "src.txt"
    source.write_bytes(b"hello world")
    dest = tmp_path / "dest.txt"

    copy_file(source, dest)

    assert dest.read_bytes() == b"hello world"


def test_copy_file_preserves_mtime(tmp_path: Path) -> None:
    source = tmp_path / "src.txt"
    source.write_bytes(b"x")
    import os
    old_time = 1_500_000_000
    os.utime(source, (old_time, old_time))
    dest = tmp_path / "dest.txt"

    copy_file(source, dest)

    assert int(dest.stat().st_mtime) == old_time


def test_copy_file_falls_back_on_permission_error(tmp_path: Path) -> None:
    source = tmp_path / "src.txt"
    source.write_bytes(b"fallback")
    dest = tmp_path / "dest.txt"

    original_copyfile = shutil.copyfile

    with (
        patch("bookery.core.filecopy.shutil.copy2", side_effect=PermissionError("chflags")),
        patch(
            "bookery.core.filecopy.shutil.copyfile",
            side_effect=original_copyfile,
        ) as mock_copyfile,
    ):
        copy_file(source, dest)

    mock_copyfile.assert_called_once()
    assert dest.read_bytes() == b"fallback"


def test_copy_file_raises_on_missing_source(tmp_path: Path) -> None:
    source = tmp_path / "nope.txt"
    dest = tmp_path / "dest.txt"

    with pytest.raises(FileNotFoundError):
        copy_file(source, dest)

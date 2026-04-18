# ABOUTME: Unit tests for convert.kepub — subprocess shell-out around kepubify.

import subprocess
from pathlib import Path
from typing import Any

import pytest

from bookery.convert.errors import KepubifyFailed, KepubifyMissing
from bookery.convert.kepub import run_kepubify


def _fake_run(target_file: Path, returncode: int = 0, stderr: str = "") -> Any:
    def fake(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        if returncode == 0:
            target_file.write_bytes(b"fake kepub")
        return subprocess.CompletedProcess(
            args=cmd, returncode=returncode, stdout="", stderr=stderr
        )

    return fake


def test_run_kepubify_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"epub")
    expected = tmp_path / "book.kepub.epub"
    monkeypatch.setattr(subprocess, "run", _fake_run(expected))

    result = run_kepubify(epub)
    assert result == expected
    assert result.exists()


def test_run_kepubify_missing_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"epub")

    def raise_missing(*_a: Any, **_k: Any) -> None:
        raise FileNotFoundError("kepubify")

    monkeypatch.setattr(subprocess, "run", raise_missing)
    with pytest.raises(KepubifyMissing):
        run_kepubify(epub)


def test_run_kepubify_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"epub")
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(tmp_path / "book.kepub.epub", returncode=2, stderr="boom"),
    )
    with pytest.raises(KepubifyFailed) as info:
        run_kepubify(epub)
    assert "boom" in str(info.value)


def test_run_kepubify_no_output_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"epub")

    def fake(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        # Simulate kepubify succeeding but writing nothing.
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(KepubifyFailed):
        run_kepubify(epub)

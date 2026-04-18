# ABOUTME: Unit tests for the kepubify subprocess wrapper used by Kobo sync.
# ABOUTME: Stubs subprocess.run / shutil.which to verify behavior without the binary.

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bookery.device.errors import KepubifyFailed, KepubifyMissing
from bookery.device.kepubify import kepubify_version, run_kepubify


class TestRunKepubify:
    def test_invokes_kepubify_and_returns_output_path(self, tmp_path: Path) -> None:
        epub = tmp_path / "book.epub"
        epub.write_bytes(b"fake epub")
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        expected = out_dir / "book.kepub.epub"

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            expected.write_bytes(b"fake kepub")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch("bookery.device.kepubify.shutil.which", return_value="/usr/bin/kepubify"),
            patch("bookery.device.kepubify.subprocess.run", side_effect=fake_run) as mock_run,
        ):
            result = run_kepubify(epub, out_dir=out_dir)

        assert result == expected
        called_cmd = mock_run.call_args.args[0]
        assert called_cmd[0] == "kepubify"
        assert "-o" in called_cmd
        # We pass the explicit output filename, not just the directory.
        # This avoids the v4.0.x `_converted` suffix and any future kepubify
        # naming changes.
        assert str(expected) in called_cmd
        assert str(epub) in called_cmd

    def test_uses_explicit_output_filename_not_directory(
        self, tmp_path: Path
    ) -> None:
        """Regression: kepubify v4.0.x writes <name>_converted.kepub.epub when
        given just a directory. We pass `-o <full filename>` to bypass that.
        """
        epub = tmp_path / "Hooked.epub"
        epub.write_bytes(b"x")
        out_dir = tmp_path / "ws"
        out_dir.mkdir()

        captured: dict[str, list[str]] = {}

        def fake_run(cmd, **_kwargs):
            captured["cmd"] = cmd
            target = Path(cmd[cmd.index("-o") + 1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"k")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch("bookery.device.kepubify.shutil.which", return_value="/usr/bin/kepubify"),
            patch("bookery.device.kepubify.subprocess.run", side_effect=fake_run),
        ):
            result = run_kepubify(epub, out_dir=out_dir)

        # The argument after `-o` must be a *file path* ending in .kepub.epub,
        # never a bare directory.
        out_arg = captured["cmd"][captured["cmd"].index("-o") + 1]
        assert out_arg.endswith(".kepub.epub")
        assert out_arg != str(out_dir)
        assert result == out_dir / "Hooked.kepub.epub"
        assert result.exists()

    def test_raises_when_binary_missing(self, tmp_path: Path) -> None:
        epub = tmp_path / "book.epub"
        epub.write_bytes(b"x")
        with (
            patch("bookery.device.kepubify.shutil.which", return_value=None),
            pytest.raises(KepubifyMissing) as exc_info,
        ):
            run_kepubify(epub, out_dir=tmp_path)
        assert exc_info.value.exit_code == 3
        assert "kepubify" in str(exc_info.value).lower()

    def test_raises_on_nonzero_exit(self, tmp_path: Path) -> None:
        epub = tmp_path / "book.epub"
        epub.write_bytes(b"x")
        err = subprocess.CalledProcessError(returncode=2, cmd=["kepubify"], stderr="boom")
        with (
            patch("bookery.device.kepubify.shutil.which", return_value="/usr/bin/kepubify"),
            patch("bookery.device.kepubify.subprocess.run", side_effect=err),
            pytest.raises(KepubifyFailed) as exc_info,
        ):
            run_kepubify(epub, out_dir=tmp_path)
        assert exc_info.value.exit_code == 1
        assert "boom" in str(exc_info.value)


class TestKepubifyVersion:
    def test_parses_version_string(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["kepubify", "--version"],
            returncode=0,
            stdout="kepubify v4.4.0\n",
            stderr="",
        )
        with (
            patch("bookery.device.kepubify.shutil.which", return_value="/usr/bin/kepubify"),
            patch("bookery.device.kepubify.subprocess.run", return_value=completed),
        ):
            assert kepubify_version() == "v4.4.0"

    def test_raises_when_missing(self) -> None:
        with (
            patch("bookery.device.kepubify.shutil.which", return_value=None),
            pytest.raises(KepubifyMissing),
        ):
            kepubify_version()

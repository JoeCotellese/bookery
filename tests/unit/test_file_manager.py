# ABOUTME: Unit tests for cross-platform file manager opener utility.
# ABOUTME: Validates platform detection and dispatch to native file manager openers.

from pathlib import Path
from unittest.mock import patch

from bookery.util.file_manager import (
    Headless,
    Opened,
    OpenerFailed,
    Platform,
    detect_platform,
    is_headless_linux,
    open_in_file_manager,
)


class TestDetectPlatform:
    def test_macos(self) -> None:
        with patch("platform.system", return_value="Darwin"):
            assert detect_platform() == Platform.MACOS

    def test_windows(self) -> None:
        with patch("platform.system", return_value="Windows"):
            assert detect_platform() == Platform.WINDOWS

    def test_linux(self) -> None:
        with (
            patch("platform.system", return_value="Linux"),
            patch(
                "bookery.util.file_manager._read_proc_version",
                return_value="Linux version 5.15.0 (gcc)",
            ),
        ):
            assert detect_platform() == Platform.LINUX

    def test_wsl(self) -> None:
        with (
            patch("platform.system", return_value="Linux"),
            patch(
                "bookery.util.file_manager._read_proc_version",
                return_value="Linux version 5.15.0-microsoft-standard-WSL2",
            ),
        ):
            assert detect_platform() == Platform.WSL


class TestIsHeadlessLinux:
    def test_headless_when_no_display_and_no_xdg_open(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("shutil.which", return_value=None),
        ):
            assert is_headless_linux() is True

    def test_not_headless_when_display_set(self) -> None:
        with (
            patch.dict("os.environ", {"DISPLAY": ":0"}, clear=True),
            patch("shutil.which", return_value="/usr/bin/xdg-open"),
        ):
            assert is_headless_linux() is False

    def test_not_headless_when_wayland_set(self) -> None:
        with (
            patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=True),
            patch("shutil.which", return_value="/usr/bin/xdg-open"),
        ):
            assert is_headless_linux() is False

    def test_headless_when_display_set_but_no_xdg_open(self) -> None:
        with (
            patch.dict("os.environ", {"DISPLAY": ":0"}, clear=True),
            patch("shutil.which", return_value=None),
        ):
            assert is_headless_linux() is True


class TestOpenInFileManager:
    def test_macos_dispatches_open(self, tmp_path: Path) -> None:
        with (
            patch(
                "bookery.util.file_manager.detect_platform",
                return_value=Platform.MACOS,
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            result = open_in_file_manager(tmp_path)

        assert isinstance(result, Opened)
        mock_run.assert_called_once_with(
            ["open", str(tmp_path)], check=True
        )

    def test_linux_dispatches_xdg_open(self, tmp_path: Path) -> None:
        with (
            patch(
                "bookery.util.file_manager.detect_platform",
                return_value=Platform.LINUX,
            ),
            patch(
                "bookery.util.file_manager.is_headless_linux",
                return_value=False,
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            result = open_in_file_manager(tmp_path)

        assert isinstance(result, Opened)
        mock_run.assert_called_once_with(
            ["xdg-open", str(tmp_path)], check=True
        )

    def test_windows_dispatches_startfile(self, tmp_path: Path) -> None:
        with (
            patch(
                "bookery.util.file_manager.detect_platform",
                return_value=Platform.WINDOWS,
            ),
            patch("os.startfile", create=True) as mock_startfile,
        ):
            result = open_in_file_manager(tmp_path)

        assert isinstance(result, Opened)
        mock_startfile.assert_called_once_with(str(tmp_path))

    def test_wsl_dispatches_explorer_with_translated_path(
        self, tmp_path: Path
    ) -> None:
        with (
            patch(
                "bookery.util.file_manager.detect_platform",
                return_value=Platform.WSL,
            ),
            patch("subprocess.run") as mock_run,
        ):
            # First call is wslpath -w to translate
            mock_run.side_effect = [
                type(
                    "R",
                    (),
                    {"stdout": "C:\\Users\\me\\book\n", "returncode": 0},
                )(),
                type("R", (), {"returncode": 0})(),
            ]
            result = open_in_file_manager(tmp_path)

        assert isinstance(result, Opened)
        assert mock_run.call_count == 2
        # second call should invoke explorer.exe with translated path
        second_call_args = mock_run.call_args_list[1][0][0]
        assert second_call_args[0] == "explorer.exe"
        assert second_call_args[1] == "C:\\Users\\me\\book"

    def test_headless_linux_returns_headless(self, tmp_path: Path) -> None:
        with (
            patch(
                "bookery.util.file_manager.detect_platform",
                return_value=Platform.LINUX,
            ),
            patch(
                "bookery.util.file_manager.is_headless_linux",
                return_value=True,
            ),
        ):
            result = open_in_file_manager(tmp_path)

        assert isinstance(result, Headless)

    def test_opener_not_found_returns_opener_failed(self, tmp_path: Path) -> None:
        with (
            patch(
                "bookery.util.file_manager.detect_platform",
                return_value=Platform.MACOS,
            ),
            patch("subprocess.run", side_effect=FileNotFoundError("open")),
        ):
            result = open_in_file_manager(tmp_path)

        assert isinstance(result, OpenerFailed)
        assert "open" in result.message

    def test_opener_nonzero_returns_opener_failed(self, tmp_path: Path) -> None:
        import subprocess

        with (
            patch(
                "bookery.util.file_manager.detect_platform",
                return_value=Platform.MACOS,
            ),
            patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(1, ["open"]),
            ),
        ):
            result = open_in_file_manager(tmp_path)

        assert isinstance(result, OpenerFailed)

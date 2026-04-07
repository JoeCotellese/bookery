# ABOUTME: Cross-platform helper to open a directory in the OS file manager.
# ABOUTME: Detects macOS, Windows, Linux, and WSL and dispatches the native opener.

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Platform(Enum):
    MACOS = "macos"
    WINDOWS = "windows"
    LINUX = "linux"
    WSL = "wsl"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Opened:
    """The path was successfully handed off to the OS file manager."""


@dataclass(frozen=True)
class Headless:
    """No graphical environment available to open a file manager."""


@dataclass(frozen=True)
class OpenerFailed:
    """The native opener could not be invoked or returned a failure."""

    message: str


OpenResult = Opened | Headless | OpenerFailed


def _read_proc_version() -> str:
    """Return the contents of /proc/version, or empty string if unavailable."""
    try:
        return Path("/proc/version").read_text(errors="ignore")
    except OSError:
        return ""


def detect_platform() -> Platform:
    """Detect which OS family we are running on, distinguishing WSL from Linux."""
    system = platform.system()
    if system == "Darwin":
        return Platform.MACOS
    if system == "Windows":
        return Platform.WINDOWS
    if system == "Linux":
        if "microsoft" in _read_proc_version().lower():
            return Platform.WSL
        return Platform.LINUX
    return Platform.UNKNOWN


def is_headless_linux() -> bool:
    """Return True if no graphical session is available to open a file manager."""
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    has_xdg_open = shutil.which("xdg-open") is not None
    return not (has_display and has_xdg_open)


def open_in_file_manager(path: Path) -> OpenResult:
    """Open ``path`` in the native file manager for the current platform."""
    plat = detect_platform()

    if plat == Platform.MACOS:
        return _run(["open", str(path)])

    if plat == Platform.WINDOWS:
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except OSError as exc:
            return OpenerFailed(str(exc))
        return Opened()

    if plat == Platform.LINUX:
        if is_headless_linux():
            return Headless()
        return _run(["xdg-open", str(path)])

    if plat == Platform.WSL:
        try:
            translated = subprocess.run(
                ["wslpath", "-w", str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            return OpenerFailed(f"wslpath failed: {exc}")
        win_path = translated.stdout.strip()
        return _run(["explorer.exe", win_path])

    return OpenerFailed(f"Unsupported platform: {plat}")


def _run(cmd: list[str]) -> OpenResult:
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        return OpenerFailed(f"opener not found: {cmd[0]} ({exc})")
    except subprocess.CalledProcessError as exc:
        return OpenerFailed(f"opener exited {exc.returncode}: {cmd[0]}")
    return Opened()

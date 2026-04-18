# ABOUTME: Kobo device sync — detects mounted readers and copies kepubs to them.
# ABOUTME: The library stays canonical EPUB; kepubify runs only inside this module.

import getpass
import platform
from collections.abc import Iterable
from pathlib import Path

KOBO_MARKER = ".kobo"


def _default_mount_roots() -> list[Path]:
    system = platform.system()
    if system == "Darwin":
        return [Path("/Volumes")]
    if system == "Linux":
        try:
            user = getpass.getuser()
        except Exception:
            user = ""
        roots = [Path("/media"), Path("/mnt")]
        if user:
            roots.extend([Path(f"/media/{user}"), Path(f"/run/media/{user}")])
        return roots
    return []


def _scan_roots(roots: Iterable[Path]) -> list[Path]:
    candidates: list[Path] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir():
                candidates.append(child)
    return candidates


def detect_mounted_kobo(
    *, candidates: Iterable[Path] | None = None
) -> Path | None:
    """Return the first mount path that contains a `.kobo/` marker, else None.

    When `candidates` is None, scans platform-default mount roots (e.g.
    /Volumes on macOS; /media/$USER and /run/media/$USER on Linux).
    """
    if candidates is None:
        candidates = _scan_roots(_default_mount_roots())
    for path in candidates:
        if not path.exists():
            continue
        if (path / KOBO_MARKER).is_dir():
            return path
    return None

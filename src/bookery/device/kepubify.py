# ABOUTME: Subprocess wrapper around the external `kepubify` binary.
# ABOUTME: Used by Kobo sync to convert canonical EPUBs into the .kepub.epub delivery format.

import shutil
import subprocess
from pathlib import Path

from bookery.device.errors import KepubifyFailed, KepubifyMissing

KEPUBIFY = "kepubify"


def _ensure_present() -> str:
    path = shutil.which(KEPUBIFY)
    if path is None:
        raise KepubifyMissing()
    return path


def run_kepubify(epub: Path, *, out_dir: Path) -> Path:
    """Run kepubify on `epub`, writing `<name>.kepub.epub` into `out_dir`.

    Passes `-o <out_dir>/<name>.kepub.epub` explicitly so we control the
    output filename. Different kepubify versions disagree on the default
    naming (v4.0.x produces `<name>_converted.kepub.epub`, newer versions
    drop the suffix), and an explicit `-o` filename short-circuits that
    inconsistency.

    Returns the path to the produced .kepub.epub file.
    """
    _ensure_present()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{epub.stem}.kepub.epub"
    try:
        subprocess.run(
            [KEPUBIFY, "-o", str(out_path), str(epub)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise KepubifyFailed(exc.stderr or str(exc)) from exc
    return out_path


def kepubify_version() -> str:
    """Return the kepubify version string (e.g. 'v4.4.0')."""
    _ensure_present()
    completed = subprocess.run(
        [KEPUBIFY, "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    text = (completed.stdout or completed.stderr or "").strip()
    # Output looks like "kepubify v4.4.0" — return the v-prefixed token if present.
    for token in text.split():
        if token.startswith("v") and any(ch.isdigit() for ch in token):
            return token
    return text

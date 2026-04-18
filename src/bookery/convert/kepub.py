# ABOUTME: Shell-out wrapper around kepubify to produce .kepub.epub variants for Kobo.
# ABOUTME: Surfaces missing-binary and non-zero-exit failures as typed ConvertErrors.

import subprocess
from pathlib import Path

from bookery.convert.errors import KepubifyFailed, KepubifyMissing


def run_kepubify(epub_path: Path, *, out_dir: Path | None = None) -> Path:
    """Run kepubify on an EPUB and return the resulting .kepub.epub path."""
    target_dir = out_dir or epub_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["kepubify", "-o", str(target_dir), str(epub_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise KepubifyMissing() from exc
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise KepubifyFailed(stderr)

    expected = target_dir / f"{epub_path.stem}.kepub.epub"
    if not expected.exists():
        candidates = list(target_dir.glob("*.kepub.epub"))
        if not candidates:
            raise KepubifyFailed(
                f"kepubify succeeded but no .kepub.epub was produced in {target_dir}"
            )
        # kepubify occasionally picks a slightly different stem; trust its output.
        expected = candidates[0]
    return expected

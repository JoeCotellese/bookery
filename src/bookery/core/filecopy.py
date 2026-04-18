# ABOUTME: Filesystem copy helper tolerant of macOS BSD file-flag permission errors.
# ABOUTME: Preserves mtime via copy2, falls back to copyfile + utime on PermissionError.

import os
import shutil
from pathlib import Path


def copy_file(source: Path, dest: Path) -> None:
    """Copy file preserving mtime, tolerant of cross-filesystem metadata quirks.

    shutil.copy2 preserves BSD file flags via chflags, which fails with
    PermissionError when copying from some network mounts on macOS. Fall back
    to a plain copy + best-effort mtime preservation when that happens.
    """
    try:
        shutil.copy2(source, dest)
    except PermissionError:
        shutil.copyfile(source, dest)
        try:
            st = source.stat()
            os.utime(dest, ns=(st.st_atime_ns, st.st_mtime_ns))
        except OSError:
            pass

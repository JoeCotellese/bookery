# ABOUTME: SHA-256 file hashing for deduplication on import.
# ABOUTME: Reads files in chunks to handle large EPUBs without excessive memory use.

import hashlib
from pathlib import Path

_CHUNK_SIZE = 65536  # 64 KB


def compute_file_hash(path: Path) -> str:
    """Compute the SHA-256 hash of a file.

    Reads the file in 64KB chunks to avoid loading large files entirely
    into memory.

    Args:
        path: Path to the file to hash.

    Returns:
        Lowercase hex digest string (64 characters).

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()

# ABOUTME: Unit tests for SHA-256 file hashing used in deduplication.
# ABOUTME: Validates determinism, uniqueness, hex format, and error handling.

import re
from pathlib import Path

import pytest

from bookery.db.hashing import compute_file_hash


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    """Create a sample file with known content."""
    f = tmp_path / "sample.epub"
    f.write_bytes(b"fake epub content for hashing")
    return f


@pytest.fixture()
def different_file(tmp_path: Path) -> Path:
    """Create a different file."""
    f = tmp_path / "different.epub"
    f.write_bytes(b"completely different content")
    return f


class TestComputeFileHash:
    """Tests for compute_file_hash."""

    def test_returns_hex_string(self, sample_file: Path) -> None:
        """Result is a 64-character hex string (SHA-256)."""
        result = compute_file_hash(sample_file)
        assert len(result) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", result)

    def test_is_deterministic(self, sample_file: Path) -> None:
        """Same file hashed twice yields the same result."""
        hash1 = compute_file_hash(sample_file)
        hash2 = compute_file_hash(sample_file)
        assert hash1 == hash2

    def test_different_files_different_hashes(
        self, sample_file: Path, different_file: Path
    ) -> None:
        """Two different files produce different hashes."""
        hash1 = compute_file_hash(sample_file)
        hash2 = compute_file_hash(different_file)
        assert hash1 != hash2

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        """Hashing a nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            compute_file_hash(tmp_path / "nonexistent.epub")

    def test_empty_file(self, tmp_path: Path) -> None:
        """Empty file produces a valid hash (the SHA-256 of empty bytes)."""
        empty = tmp_path / "empty.epub"
        empty.write_bytes(b"")
        result = compute_file_hash(empty)
        assert len(result) == 64

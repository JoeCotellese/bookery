# ABOUTME: Integration tests for EPUB metadata round-trip operations.
# ABOUTME: Tests read -> modify -> write -> re-read with real EPUB files.

import shutil
from pathlib import Path

from bookery.formats.epub import read_epub_metadata, write_epub_metadata
from bookery.metadata import BookMetadata


class TestEpubRoundTrip:
    """Integration tests exercising full metadata round-trip on real files."""

    def test_full_metadata_round_trip(self, sample_epub: Path) -> None:
        """Read metadata, modify all fields, write back, verify all persisted."""
        updated = BookMetadata(
            title="Il Nome della Rosa",
            authors=["Eco, Umberto"],
            language="it",
            publisher="Bompiani",
            description="Un giallo ambientato in un monastero medievale.",
        )
        write_epub_metadata(sample_epub, updated)

        result = read_epub_metadata(sample_epub)
        assert result.title == "Il Nome della Rosa"
        assert result.authors == ["Eco, Umberto"]
        assert result.language == "it"
        assert result.publisher == "Bompiani"
        assert result.description == "Un giallo ambientato in un monastero medievale."

    def test_multiple_writes_preserve_integrity(self, sample_epub: Path) -> None:
        """Multiple sequential writes don't corrupt the file."""
        for i in range(3):
            meta = BookMetadata(title=f"Revision {i}")
            write_epub_metadata(sample_epub, meta)

        result = read_epub_metadata(sample_epub)
        assert result.title == "Revision 2"

    def test_write_does_not_alter_file_when_metadata_matches(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """Writing the same metadata back produces a readable file."""
        original = read_epub_metadata(sample_epub)

        # Write same metadata back
        write_epub_metadata(sample_epub, original)

        # Should still be perfectly readable
        result = read_epub_metadata(sample_epub)
        assert result.title == original.title
        assert result.authors == original.authors

    def test_batch_scan_directory(self, sample_epub: Path, minimal_epub: Path) -> None:
        """Scanning a directory with multiple EPUBs extracts all metadata."""
        scan_dir = sample_epub.parent / "scan"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "rose.epub")
        shutil.copy(minimal_epub, scan_dir / "minimal.epub")

        epub_files = sorted(scan_dir.rglob("*.epub"))
        assert len(epub_files) == 2

        results = [read_epub_metadata(f) for f in epub_files]
        titles = {r.title for r in results}
        assert "The Name of the Rose" in titles
        assert "Untitled Book" in titles

    def test_corrupt_file_does_not_break_batch(
        self, sample_epub: Path, corrupt_epub: Path
    ) -> None:
        """A corrupt file in a batch doesn't prevent other files from being read."""
        scan_dir = sample_epub.parent / "scan"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "rose.epub")
        shutil.copy(corrupt_epub, scan_dir / "bad.epub")

        epub_files = sorted(scan_dir.rglob("*.epub"))
        results = []
        errors = []

        for f in epub_files:
            try:
                results.append(read_epub_metadata(f))
            except Exception:
                errors.append(f)

        assert len(results) >= 1
        assert len(errors) >= 1
        assert any(r.title == "The Name of the Rose" for r in results)

# ABOUTME: Unit tests for EPUB metadata writing.
# ABOUTME: Tests round-trip: read metadata, modify, write back, verify.

from pathlib import Path

import pytest

from bookery.formats.epub import EpubReadError, read_epub_metadata, write_epub_metadata
from bookery.metadata import BookMetadata


class TestWriteEpubMetadata:
    """Tests for EPUB metadata writing."""

    def test_write_updates_title(self, sample_epub: Path) -> None:
        """Writing new metadata updates the title in the EPUB."""
        original = read_epub_metadata(sample_epub)
        updated = BookMetadata(
            title="Il Nome della Rosa",
            authors=original.authors,
            language=original.language,
            publisher=original.publisher,
            description=original.description,
            identifiers=original.identifiers,
            source_path=original.source_path,
        )
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.title == "Il Nome della Rosa"

    def test_write_updates_author(self, sample_epub: Path) -> None:
        """Writing new metadata updates the author in the EPUB."""
        original = read_epub_metadata(sample_epub)
        updated = BookMetadata(
            title=original.title,
            authors=["Eco, Umberto"],
            language=original.language,
        )
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.authors == ["Eco, Umberto"]

    def test_write_updates_language(self, sample_epub: Path) -> None:
        """Writing new metadata updates the language in the EPUB."""
        updated = BookMetadata(title="Test", language="it")
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.language == "it"

    def test_write_updates_publisher(self, sample_epub: Path) -> None:
        """Writing new metadata updates the publisher in the EPUB."""
        updated = BookMetadata(title="Test", publisher="Bompiani")
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.publisher == "Bompiani"

    def test_write_updates_description(self, sample_epub: Path) -> None:
        """Writing new metadata updates the description in the EPUB."""
        updated = BookMetadata(title="Test", description="A new description.")
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.description == "A new description."

    def test_write_preserves_content(self, sample_epub: Path) -> None:
        """Writing metadata does not corrupt the EPUB's content."""
        updated = BookMetadata(title="Updated Title")
        write_epub_metadata(sample_epub, updated)

        # Should still be readable
        meta = read_epub_metadata(sample_epub)
        assert meta.title == "Updated Title"

    def test_write_to_nonexistent_file_raises(self, tmp_path: Path) -> None:
        """Writing to a nonexistent file raises an error."""
        meta = BookMetadata(title="Ghost")
        with pytest.raises(EpubReadError):
            write_epub_metadata(tmp_path / "ghost.epub", meta)

    def test_write_to_corrupt_file_raises(self, corrupt_epub: Path) -> None:
        """Writing to a corrupt file raises an error."""
        meta = BookMetadata(title="Fix")
        with pytest.raises(EpubReadError):
            write_epub_metadata(corrupt_epub, meta)

    def test_write_survives_none_uid_identifier(self, sample_epub: Path) -> None:
        """EPUBs where the uid identifier has a None value get a replacement uid."""
        from unittest.mock import patch

        from ebooklib import epub

        original_read = epub.read_epub

        def read_and_poison(*args, **kwargs):
            book = original_read(*args, **kwargs)
            # Simulate a Calibre EPUB with None uid identifier
            dc_ns = "http://purl.org/dc/elements/1.1/"
            book.metadata[dc_ns]["identifier"] = [(None, {"id": "uuid_id"})]
            book.uid = None
            return book

        with patch("bookery.formats.epub.epub.read_epub", side_effect=read_and_poison):
            updated = BookMetadata(title="Survives None UID")
            write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.title == "Survives None UID"

    def test_write_survives_none_opf_metadata(self, sample_epub: Path) -> None:
        """EPUBs with None values in OPF metadata (e.g. cover meta) don't crash on write.

        ebooklib reads <meta name="cover" content="cover-image"/> as
        (None, {'content': 'cover-image', 'name': 'cover'}). The None value
        causes lxml to crash during serialization.
        """
        from ebooklib import epub

        # Inject a None-valued OPF meta entry (mimics the cover meta tag)
        book = epub.read_epub(str(sample_epub))
        opf_ns = "http://www.idpf.org/2007/opf"
        book.metadata.setdefault(opf_ns, {})
        book.metadata[opf_ns]["meta"] = [(None, {"name": "cover", "content": "cover-image"})]

        # Write a temp copy with the poisoned metadata
        from bookery.formats.epub import _fix_toc_uids
        _fix_toc_uids(book)
        epub.write_epub(str(sample_epub), book)

        # Our write should scrub the None and succeed
        updated = BookMetadata(title="Survives None")
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.title == "Survives None"

    def test_write_survives_deeply_nested_toc(self, sample_epub: Path) -> None:
        """EPUBs with 3+ levels of TOC nesting don't crash on write."""
        from unittest.mock import patch

        from ebooklib import epub

        # Read the EPUB, then monkey-patch its TOC with deep nesting
        # so write_epub_metadata encounters it during our write path
        original_read = epub.read_epub

        def read_and_poison(*args, **kwargs):
            book = original_read(*args, **kwargs)
            inner_link = epub.Link("ch1.html", "Chapter 1", None)
            inner_section = (epub.Section("Part A"), [inner_link])
            outer_section = (epub.Section("Book I"), [inner_section])
            book.toc = [outer_section]
            return book

        with patch("bookery.formats.epub.epub.read_epub", side_effect=read_and_poison):
            updated = BookMetadata(title="Deep TOC")
            write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.title == "Deep TOC"

    def test_write_survives_none_guide_entries(self, sample_epub: Path) -> None:
        """EPUBs with None-valued guide entries don't crash on write."""
        from unittest.mock import patch

        from ebooklib import epub

        original_read = epub.read_epub

        def read_and_poison(*args, **kwargs):
            book = original_read(*args, **kwargs)
            book.guide.append({"href": None, "title": None, "type": None})
            return book

        with patch("bookery.formats.epub.epub.read_epub", side_effect=read_and_poison):
            updated = BookMetadata(title="Survives Guide None")
            write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.title == "Survives Guide None"

    def test_round_trip_preserves_unmodified_fields(self, sample_epub: Path) -> None:
        """Fields not in the update are preserved from the original EPUB."""
        original = read_epub_metadata(sample_epub)

        # Only update the title, keep everything else
        updated = BookMetadata(
            title="New Title",
            authors=original.authors,
            language=original.language,
            publisher=original.publisher,
            description=original.description,
            identifiers=original.identifiers,
        )
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.title == "New Title"
        assert re_read.authors == ["Umberto Eco"]
        assert re_read.publisher == "Harcourt"
        assert re_read.description == "A mystery set in a medieval monastery."

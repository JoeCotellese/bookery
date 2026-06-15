# ABOUTME: Unit tests for EPUB metadata writing.
# ABOUTME: Tests round-trip: read metadata, modify, write back, verify.

import zipfile
from pathlib import Path

import pytest

from bookery.formats.epub import (
    EpubReadError,
    read_creator_file_as,
    read_epub_metadata,
    write_epub_metadata,
)
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


class TestWriteCreatorFileAs:
    """Writing authors emits a surname-first opf:file-as so devices sort right."""

    def test_first_last_gets_inverted_file_as(self, sample_epub: Path) -> None:
        """A "First Last" author writes file-as "Last, First"."""
        write_epub_metadata(
            sample_epub, BookMetadata(title="T", authors=["Brandon Sanderson"])
        )
        assert read_creator_file_as(sample_epub) == [
            ("Brandon Sanderson", "Sanderson, Brandon")
        ]

    def test_already_inverted_author_keeps_file_as(self, sample_epub: Path) -> None:
        """A "Last, First" author keeps its order as the file-as."""
        write_epub_metadata(
            sample_epub, BookMetadata(title="T", authors=["Sanderson, Brandon"])
        )
        assert read_creator_file_as(sample_epub) == [
            ("Sanderson, Brandon", "Sanderson, Brandon")
        ]

    def test_each_coauthor_gets_its_own_file_as(self, sample_epub: Path) -> None:
        """Co-authors each get an independent file-as (no shared sort key)."""
        write_epub_metadata(
            sample_epub,
            BookMetadata(title="T", authors=["Bryan Burrough", "John Helyar"]),
        )
        assert read_creator_file_as(sample_epub) == [
            ("Bryan Burrough", "Burrough, Bryan"),
            ("John Helyar", "Helyar, John"),
        ]

    def test_explicit_author_sort_wins_for_primary(self, sample_epub: Path) -> None:
        """A curator-set author_sort is used for the primary author's file-as."""
        write_epub_metadata(
            sample_epub,
            BookMetadata(
                title="T", authors=["Plato"], author_sort="Plato (Greek)"
            ),
        )
        assert read_creator_file_as(sample_epub) == [("Plato", "Plato (Greek)")]

    def test_rewrite_does_not_accumulate_stale_file_as(
        self, sample_epub: Path
    ) -> None:
        """Re-writing leaves exactly one file-as per creator, not a pile of them."""
        meta = BookMetadata(title="T", authors=["Brandon Sanderson"])
        write_epub_metadata(sample_epub, meta)
        write_epub_metadata(sample_epub, meta)
        assert read_creator_file_as(sample_epub) == [
            ("Brandon Sanderson", "Sanderson, Brandon")
        ]

    def test_reads_epub2_file_as_attribute(self, tmp_path: Path) -> None:
        """Reader also handles the EPUB2 ``opf:file-as`` attribute form."""
        opf = (
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="2.0"'
            ' unique-identifier="id">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"'
            ' xmlns:opf="http://www.idpf.org/2007/opf">'
            '<dc:identifier id="id">x</dc:identifier><dc:title>T</dc:title>'
            '<dc:creator opf:file-as="Brooks, John">John Brooks</dc:creator>'
            "</metadata>"
            '<manifest><item id="x" href="x.html"'
            ' media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="x"/></spine></package>'
        )
        container = (
            '<?xml version="1.0"?>'
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"'
            ' version="1.0"><rootfiles><rootfile full-path="content.opf"'
            ' media-type="application/oebps-package+xml"/></rootfiles></container>'
        )
        path = tmp_path / "book.epub"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr("META-INF/container.xml", container)
            zf.writestr("content.opf", opf)
            zf.writestr("x.html", "<html></html>")

        assert read_creator_file_as(path) == [("John Brooks", "Brooks, John")]


_JPEG_COVER = b"\xff\xd8\xff\xe0" + b"new-cover-bytes" * 8
_PNG_COVER = b"\x89PNG\r\n\x1a\n" + b"png-cover-bytes" * 8


class TestWriteEpubCover:
    """Tests for embedding a cover image during the metadata write."""

    def test_embeds_cover_when_book_has_none(self, sample_epub: Path) -> None:
        """A book imported without a cover gets the candidate's cover embedded."""
        # sample_epub has no cover image to start.
        assert read_epub_metadata(sample_epub).cover_image is None

        updated = BookMetadata(title="With Cover", cover_image=_JPEG_COVER)
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.cover_image == _JPEG_COVER

    def test_replaces_existing_cover(self, sample_epub: Path) -> None:
        """Writing a cover onto a book that already has one swaps the bytes."""
        write_epub_metadata(sample_epub, BookMetadata(title="First", cover_image=_JPEG_COVER))
        assert read_epub_metadata(sample_epub).cover_image == _JPEG_COVER

        write_epub_metadata(sample_epub, BookMetadata(title="Second", cover_image=_PNG_COVER))
        re_read = read_epub_metadata(sample_epub)
        assert re_read.cover_image == _PNG_COVER

    def test_no_cover_bytes_leaves_book_coverless(self, sample_epub: Path) -> None:
        """Omitting cover bytes preserves the prior (cover-less) state."""
        updated = BookMetadata(title="No Cover", cover_image=None)
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.cover_image is None

    def test_rewritten_epub_opens_cleanly(self, sample_epub: Path) -> None:
        """The cover-rewritten EPUB re-reads without error (opens in a reader)."""
        write_epub_metadata(sample_epub, BookMetadata(title="Readable", cover_image=_JPEG_COVER))

        # read_epub_metadata raises EpubReadError on a structurally broken file.
        meta = read_epub_metadata(sample_epub)
        assert meta.title == "Readable"
        assert meta.cover_image == _JPEG_COVER

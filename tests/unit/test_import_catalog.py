# ABOUTME: Unit tests for the import pipeline (copy-by-default into library_root).
# ABOUTME: Validates file cataloging, copy/move behavior, dedup, errors, and summaries.

from pathlib import Path

import pytest
from ebooklib import epub

from bookery.core.importer import MatchResult, import_books
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "import_test.db")
    return LibraryCatalog(conn)


@pytest.fixture()
def library_root(tmp_path: Path) -> Path:
    """Provide a temporary library_root directory."""
    root = tmp_path / "lib"
    root.mkdir()
    return root


def _make_epub(path: Path, title: str, author: str | None = None) -> Path:
    """Create a minimal EPUB with the given title."""
    book = epub.EpubBook()
    book.set_identifier(f"id-{title}")
    book.set_title(title)
    book.set_language("en")
    if author:
        book.add_author(author)

    chapter = epub.EpubHtml(
        title="Chapter 1", file_name="chap01.xhtml", lang="en",
    )
    chapter.content = (
        b"<html><body><h1>Chapter 1</h1>"
        b"<p>Content for " + title.encode() + b".</p>"
        b"</body></html>"
    )
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(path), book)
    return path


class TestImportBooks:
    """Tests for import_books function."""

    def test_import_single_file(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """Importing a single EPUB adds one record to the catalog."""
        epub_path = _make_epub(tmp_path / "book.epub", "Test Book", "Author")
        result = import_books([epub_path], catalog, library_root=library_root)

        assert result.added == 1
        assert result.skipped == 0
        assert result.errors == 0

        records = catalog.list_all()
        assert len(records) == 1
        assert records[0].metadata.title == "Test Book"

    def test_import_directory_of_files(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """Importing multiple EPUBs adds all to the catalog."""
        for i in range(3):
            _make_epub(tmp_path / f"book_{i}.epub", f"Book {i}")

        paths = sorted(tmp_path.glob("*.epub"))
        result = import_books(paths, catalog, library_root=library_root)

        assert result.added == 3
        records = catalog.list_all()
        assert len(records) == 3

    def test_import_skips_duplicates(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """Importing the same file twice adds it once and skips the second."""
        epub_path = _make_epub(tmp_path / "book.epub", "Test Book")

        result1 = import_books([epub_path], catalog, library_root=library_root)
        result2 = import_books([epub_path], catalog, library_root=library_root)

        assert result1.added == 1
        assert result2.added == 0
        assert result2.skipped == 1

        records = catalog.list_all()
        assert len(records) == 1

    def test_import_records_source_path(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """source_path in the DB matches the original file location."""
        epub_path = _make_epub(tmp_path / "book.epub", "Test Book")
        import_books([epub_path], catalog, library_root=library_root)

        records = catalog.list_all()
        assert len(records) == 1
        assert records[0].source_path == epub_path

    def test_import_stores_file_hash(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """File hash is computed and stored in the catalog."""
        epub_path = _make_epub(tmp_path / "book.epub", "Test Book")
        import_books([epub_path], catalog, library_root=library_root)

        records = catalog.list_all()
        assert len(records) == 1
        assert len(records[0].file_hash) == 64  # SHA-256 hex

    def test_import_handles_corrupt_files(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """Corrupt files are logged as errors; valid files still imported."""
        good = _make_epub(tmp_path / "good.epub", "Good Book")
        bad = tmp_path / "bad.epub"
        bad.write_text("not a valid epub")

        result = import_books([good, bad], catalog, library_root=library_root)

        assert result.added == 1
        assert result.errors == 1
        assert len(result.error_details) == 1
        assert result.error_details[0][0] == bad

    def test_import_returns_result_summary(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """ImportResult has correct totals for mixed outcomes."""
        epub1 = _make_epub(tmp_path / "a.epub", "Book A")
        epub2 = _make_epub(tmp_path / "b.epub", "Book B")
        corrupt = tmp_path / "c.epub"
        corrupt.write_text("corrupt")

        # First import: 2 added, 1 error
        result1 = import_books(
            [epub1, epub2, corrupt], catalog, library_root=library_root,
        )
        assert result1.added == 2
        assert result1.errors == 1
        assert result1.skipped == 0

        # Second import: 0 added, 2 skipped, 1 error
        result2 = import_books(
            [epub1, epub2, corrupt], catalog, library_root=library_root,
        )
        assert result2.added == 0
        assert result2.skipped == 2
        assert result2.errors == 1


class TestImportCopyByDefault:
    """Tests for copy-by-default behavior added in #63."""

    def test_import_copies_to_library_root_by_default(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """Import copies source into library_root and records output_path."""
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        epub_path = _make_epub(source_dir / "book.epub", "Test Book", "Alice Adams")

        import_books([epub_path], catalog, library_root=library_root)

        records = catalog.list_all()
        assert len(records) == 1
        out = records[0].output_path
        assert out is not None
        assert out.exists()
        assert library_root in out.parents

    def test_import_preserves_source_by_default(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """Source file is preserved when move is False."""
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        epub_path = _make_epub(source_dir / "book.epub", "Test Book", "Alice Adams")

        import_books([epub_path], catalog, library_root=library_root)

        assert epub_path.exists()

    def test_import_move_deletes_source_after_copy(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """With move=True, source is removed after successful catalog."""
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        epub_path = _make_epub(source_dir / "book.epub", "Test Book", "Alice Adams")

        import_books(
            [epub_path], catalog, library_root=library_root, move=True,
        )

        assert not epub_path.exists()
        records = catalog.list_all()
        assert records[0].output_path is not None
        assert records[0].output_path.exists()

    def test_import_idempotent_when_source_inside_library_root(
        self, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """File already inside library_root is cataloged in place, no copy."""
        author_dir = library_root / "Adams, Alice"
        author_dir.mkdir()
        epub_path = _make_epub(author_dir / "Existing.epub", "Existing", "Alice Adams")

        import_books([epub_path], catalog, library_root=library_root)

        records = catalog.list_all()
        assert records[0].source_path == epub_path
        assert records[0].output_path == epub_path
        # File is still there and only once — no duplicate
        assert len(list(library_root.rglob("*.epub"))) == 1

    def test_import_move_preserves_source_when_idempotent(
        self, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """--move on an idempotent file must NOT delete it (it's the library copy)."""
        author_dir = library_root / "Adams, Alice"
        author_dir.mkdir()
        epub_path = _make_epub(author_dir / "Existing.epub", "Existing", "Alice Adams")

        import_books(
            [epub_path], catalog, library_root=library_root, move=True,
        )

        assert epub_path.exists()

    def test_import_collision_resolved_with_suffix(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """Existing file at target gets _1 suffix via resolve_collision."""
        # Pre-populate library with a file that would collide on target path
        author_dir = library_root / "Adams, Alice"
        author_dir.mkdir()
        existing = _make_epub(author_dir / "Test Book.epub", "Occupier", "Alice Adams")
        assert existing.exists()

        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        new_epub = _make_epub(source_dir / "incoming.epub", "Test Book", "Alice Adams")

        import_books([new_epub], catalog, library_root=library_root)

        # Occupier still there, new copy written with suffix
        assert existing.exists()
        epubs = sorted(library_root.rglob("*.epub"))
        assert len(epubs) == 2

    def test_import_match_path_not_double_copied(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
    ) -> None:
        """When match_fn returns an output_path, import_books does not recopy."""
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        epub_path = _make_epub(source_dir / "book.epub", "Test Book", "Alice Adams")

        # Simulate what the match pipeline would produce: a copy already written
        match_copy = library_root / "Adams, Alice" / "Matched.epub"
        match_copy.parent.mkdir(parents=True, exist_ok=True)
        match_copy.write_bytes(epub_path.read_bytes())

        def match_fn(metadata, path):
            return MatchResult(metadata=metadata, output_path=match_copy)

        import_books(
            [epub_path], catalog, library_root=library_root, match_fn=match_fn,
        )

        records = catalog.list_all()
        assert records[0].output_path == match_copy
        # Only the one copy exists in library (no additional build_output_path copy)
        assert len(list(library_root.rglob("*.epub"))) == 1

    def test_import_copy_failure_records_error(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """OSError during copy is recorded as an error, does not crash."""
        from bookery.core import importer

        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        epub_path = _make_epub(source_dir / "book.epub", "Test Book", "Alice Adams")

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(importer, "copy_file", boom)

        result = import_books([epub_path], catalog, library_root=library_root)

        assert result.errors == 1
        assert result.added == 0
        assert catalog.list_all() == []

    def test_import_move_failure_warns_but_succeeds(
        self, tmp_path: Path, catalog: LibraryCatalog, library_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If unlink after copy fails, book is still cataloged."""
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        epub_path = _make_epub(source_dir / "book.epub", "Test Book", "Alice Adams")

        original_unlink = Path.unlink

        def failing_unlink(self, *args, **kwargs):
            if self == epub_path:
                raise OSError("read-only fs")
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", failing_unlink)

        result = import_books(
            [epub_path], catalog, library_root=library_root, move=True,
        )

        assert result.added == 1
        assert result.errors == 0

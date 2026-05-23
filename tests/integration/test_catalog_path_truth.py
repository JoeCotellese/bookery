# ABOUTME: Regression guard locking the invariant that unmatched imports
# ABOUTME: always populate books.output_path with a real file under library_root.

from pathlib import Path

from ebooklib import epub

from bookery.core.importer import import_books
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library


def _make_epub(path: Path, title: str, author: str | None = None) -> Path:
    """Create a minimal EPUB for catalog-path-truth checks."""
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


class TestImporterOutputPath:
    """Lock in the output_path invariant for unmatched imports (issue #59).

    Plan-05 cluster: the importer must always set books.output_path to a real
    file under library_root, even when no match pipeline runs. This guards
    against a future refactor silently leaving output_path NULL, which would
    poison downstream lookups (web UI, sync, vault export).

    A sibling branch (feature/64-matched-signal) may share this file; this
    class is namespaced to keep both PRs mergeable.
    """

    def test_unmatched_import_populates_output_path_under_library_root(
        self, tmp_path: Path,
    ) -> None:
        """Importing without --match sets output_path to a real file in library_root."""
        db_path = tmp_path / "lib.db"
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        library_root = tmp_path / "lib"
        library_root.mkdir()

        epub_path = _make_epub(
            source_dir / "rose.epub", "The Name of the Rose", "Umberto Eco",
        )

        conn = open_library(db_path)
        try:
            catalog = LibraryCatalog(conn)
            result = import_books(
                [epub_path], catalog, library_root=library_root,
            )

            assert result.added == 1
            assert result.errors == 0

            records = catalog.list_all()
            assert len(records) == 1

            output_path = records[0].output_path
            # Invariant 1: catalog row has output_path populated.
            assert output_path is not None, (
                "unmatched import left output_path NULL — regression on #59"
            )
            # Invariant 2: output_path resolves under library_root.
            resolved_root = library_root.resolve()
            assert output_path.resolve().is_relative_to(resolved_root), (
                f"output_path {output_path} is not under library_root "
                f"{library_root}"
            )
            # Invariant 3: the file actually exists on disk at output_path.
            assert output_path.exists(), (
                f"output_path {output_path} does not exist on disk"
            )
        finally:
            conn.close()

    def test_unmatched_import_of_multiple_files_all_have_output_paths(
        self, tmp_path: Path,
    ) -> None:
        """Every cataloged book from an unmatched batch import has output_path set."""
        db_path = tmp_path / "lib.db"
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        library_root = tmp_path / "lib"
        library_root.mkdir()

        _make_epub(source_dir / "a.epub", "Alpha", "Author A")
        _make_epub(source_dir / "b.epub", "Beta", "Author B")
        _make_epub(source_dir / "c.epub", "Gamma", "Author C")
        paths = sorted(source_dir.glob("*.epub"))

        conn = open_library(db_path)
        try:
            catalog = LibraryCatalog(conn)
            result = import_books(
                paths, catalog, library_root=library_root,
            )

            assert result.added == 3
            records = catalog.list_all()
            assert len(records) == 3

            resolved_root = library_root.resolve()
            for record in records:
                output_path = record.output_path
                assert output_path is not None, (
                    f"book {record.metadata.title!r} left output_path NULL"
                )
                assert output_path.resolve().is_relative_to(resolved_root)
                assert output_path.exists()
        finally:
            conn.close()

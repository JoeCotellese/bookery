# ABOUTME: Integration tests for the tagging workflow across catalog operations.
# ABOUTME: Tests tag lifecycle including add, query, remove, and cascading deletes.

from pathlib import Path

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


class TestTagsWorkflow:
    """Integration tests for end-to-end tagging workflows."""

    def test_tag_multiple_books_and_query(self, tmp_path: Path) -> None:
        """Tag several books, then query by tag."""
        conn = open_library(tmp_path / "workflow.db")
        catalog = LibraryCatalog(conn)

        id1 = catalog.add_book(
            BookMetadata(title="Dune", source_path=Path("/dune.epub")),
            file_hash="dune_h",
        )
        id2 = catalog.add_book(
            BookMetadata(title="Neuromancer", source_path=Path("/neuro.epub")),
            file_hash="neuro_h",
        )
        id3 = catalog.add_book(
            BookMetadata(title="Pride and Prejudice", source_path=Path("/pp.epub")),
            file_hash="pp_h",
        )

        catalog.add_tag(id1, "sci-fi")
        catalog.add_tag(id2, "sci-fi")
        catalog.add_tag(id3, "romance")
        catalog.add_tag(id1, "classic")
        catalog.add_tag(id3, "classic")

        sci_fi_books = catalog.get_books_by_tag("sci-fi")
        assert len(sci_fi_books) == 2
        titles = {b.metadata.title for b in sci_fi_books}
        assert titles == {"Dune", "Neuromancer"}

        classics = catalog.get_books_by_tag("classic")
        assert len(classics) == 2
        titles = {b.metadata.title for b in classics}
        assert titles == {"Dune", "Pride and Prejudice"}

        all_tags = catalog.list_tags()
        assert len(all_tags) == 3
        conn.close()

    def test_delete_book_removes_tag_associations(self, tmp_path: Path) -> None:
        """Deleting a book cascades to remove its tag associations."""
        conn = open_library(tmp_path / "cascade.db")
        catalog = LibraryCatalog(conn)

        book_id = catalog.add_book(
            BookMetadata(title="Ephemeral", source_path=Path("/eph.epub")),
            file_hash="eph_h",
        )
        catalog.add_tag(book_id, "temporary")
        catalog.delete_book(book_id)

        # Tag still exists but has zero books
        tags = catalog.list_tags()
        assert len(tags) == 0  # list_tags only shows tags with book counts > 0
        conn.close()

    def test_add_remove_add_cycle(self, tmp_path: Path) -> None:
        """Tags can be removed and re-added without issues."""
        conn = open_library(tmp_path / "cycle.db")
        catalog = LibraryCatalog(conn)

        book_id = catalog.add_book(
            BookMetadata(title="Cyclical", source_path=Path("/cyc.epub")),
            file_hash="cyc_h",
        )
        catalog.add_tag(book_id, "fleeting")
        catalog.remove_tag(book_id, "fleeting")
        catalog.add_tag(book_id, "fleeting")

        tags = catalog.get_tags_for_book(book_id)
        assert tags == ["fleeting"]
        conn.close()

    def test_shared_tag_across_books(self, tmp_path: Path) -> None:
        """Multiple books share the same tag without duplication."""
        conn = open_library(tmp_path / "shared.db")
        catalog = LibraryCatalog(conn)

        ids = []
        for i in range(5):
            ids.append(
                catalog.add_book(
                    BookMetadata(title=f"Book {i}", source_path=Path(f"/b{i}.epub")),
                    file_hash=f"hash_{i}",
                )
            )

        for book_id in ids:
            catalog.add_tag(book_id, "collection")

        # Only one tag row exists
        all_tags = catalog.list_tags()
        assert len(all_tags) == 1
        assert all_tags[0] == ("collection", 5)
        conn.close()

# ABOUTME: Tests for the /books/<id>/cover route, list thumbnail, and detail hero.
# ABOUTME: Covers happy path, 404, placeholder fallback, cache headers, template wiring.

from pathlib import Path

import pytest
from ebooklib import epub

from tests.web.conftest import make_book


def _epub_with_cover(path: Path) -> Path:
    book = epub.EpubBook()
    book.set_identifier("route-fixture-id")
    book.set_title("Route Fixture")
    book.set_language("en")
    book.add_author("Test Author")

    jpeg = b"\xff\xd8\xff\xe0" + b"route-cover-bytes" * 4
    book.set_cover("cover.jpg", jpeg)

    chapter = epub.EpubHtml(title="Chapter 1", file_name="chap01.xhtml", lang="en")
    chapter.content = b"<html><body><p>x</p></body></html>"
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(path), book)
    return path


@pytest.fixture
def library_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setenv("BOOKERY_LIBRARY_ROOT", str(root))
    return root


class TestCoverRoute:
    def test_returns_cover_bytes_for_book_with_cover(
        self, mock_catalog, client, library_root: Path, tmp_path: Path
    ) -> None:
        epub_path = _epub_with_cover(tmp_path / "fixture.epub")
        mock_catalog.get_by_id.return_value = make_book(1, source_path=epub_path)

        response = client.get("/books/1/cover")

        assert response.status_code == 200
        assert response.content_type.startswith("image/jpeg")
        assert response.data.startswith(b"\xff\xd8\xff")

    def test_sets_cache_control_header(
        self, mock_catalog, client, library_root: Path, tmp_path: Path
    ) -> None:
        epub_path = _epub_with_cover(tmp_path / "fixture.epub")
        mock_catalog.get_by_id.return_value = make_book(1, source_path=epub_path)

        response = client.get("/books/1/cover")

        cache_control = response.headers.get("Cache-Control", "")
        assert "max-age=86400" in cache_control
        assert "public" in cache_control

    def test_404_for_unknown_book(self, mock_catalog, client, library_root: Path) -> None:
        mock_catalog.get_by_id.return_value = None
        response = client.get("/books/999/cover")
        assert response.status_code == 404

    def test_returns_placeholder_when_book_has_no_cover(
        self, mock_catalog, client, library_root: Path, tmp_path: Path
    ) -> None:
        # Build an EPUB without a cover image declared.
        book = epub.EpubBook()
        book.set_identifier("nope")
        book.set_title("Nope")
        book.set_language("en")
        book.add_author("Anon")
        chapter = epub.EpubHtml(title="c", file_name="c.xhtml", lang="en")
        chapter.content = b"<html><body><p>x</p></body></html>"
        book.add_item(chapter)
        book.toc = [epub.Link("c.xhtml", "c", "c")]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", chapter]
        path = tmp_path / "nocover.epub"
        epub.write_epub(str(path), book)

        mock_catalog.get_by_id.return_value = make_book(1, source_path=path)

        response = client.get("/books/1/cover")
        assert response.status_code == 200
        assert response.content_type.startswith("image/svg+xml")
        # Placeholder SVG carries a recognizable marker.
        assert b"<svg" in response.data

    def test_returns_placeholder_when_source_file_missing(
        self, mock_catalog, client, library_root: Path
    ) -> None:
        mock_catalog.get_by_id.return_value = make_book(
            1, source_path=Path("/nonexistent/missing.epub")
        )

        response = client.get("/books/1/cover")
        assert response.status_code == 200
        assert response.content_type.startswith("image/svg+xml")

    def test_prefers_output_path_over_source_path(
        self, mock_catalog, client, library_root: Path, tmp_path: Path
    ) -> None:
        # source_path points at a missing file; output_path has the real EPUB.
        output_epub = _epub_with_cover(tmp_path / "output.epub")
        mock_catalog.get_by_id.return_value = make_book(
            1,
            source_path=Path("/nonexistent/source.epub"),
            output_path=output_epub,
        )

        response = client.get("/books/1/cover")
        assert response.status_code == 200
        assert response.content_type.startswith("image/jpeg")


class TestListThumbnail:
    def test_list_renders_lazy_loading_thumbnail_per_book(self, mock_catalog, client) -> None:
        mock_catalog.browse.return_value = (
            [make_book(1, title="Dune"), make_book(2, title="Foundation")],
            2,
        )

        html = client.get("/books").data.decode()

        # One <img> per book with lazy loading and the cover URL.
        assert html.count('loading="lazy"') >= 2
        assert "/books/1/cover" in html
        assert "/books/2/cover" in html
        # Thumb class is present for CSS sizing.
        assert "book-cover-thumb" in html


class TestDetailHero:
    def test_detail_renders_hero_cover(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune")

        html = client.get("/books/1").data.decode()

        assert "/books/1/cover" in html
        assert "book-cover-hero" in html

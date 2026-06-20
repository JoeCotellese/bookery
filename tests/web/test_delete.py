# ABOUTME: Tests for the web delete flow (issue #113) — confirm panel + POST handler.
# ABOUTME: Exercises GET confirm rendering, POST remove modes, flashes, and HX-Redirect.

from pathlib import Path
from unittest.mock import patch

from bookery.core.remove import RemoveResult
from tests.web.conftest import make_book


def _build_result(
    *,
    book_id: int = 1,
    title: str = "Dune",
    author: str = "Herbert, Frank",
    file_path: Path | None = Path("/library/Herbert/Dune/dune.epub"),
    file_removed: bool = True,
    siblings_removed: tuple[Path, ...] = (),
    warnings: tuple[str, ...] = (),
) -> RemoveResult:
    return RemoveResult(
        book_id=book_id,
        title=title,
        author=author,
        file_path=file_path,
        file_removed=file_removed,
        siblings_removed=siblings_removed,
        warnings=warnings,
    )


class TestDeleteConfirmGet:
    def test_renders_title_author_path(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(
            1,
            title="Dune",
            authors=["Herbert, Frank"],
            output_path=Path("/library/Herbert/Dune/dune.epub"),
        )
        mock_catalog._conn.execute.return_value.fetchone.return_value = (0,)

        html = client.get("/books/1/delete").data.decode()

        assert "Delete this book?" in html
        assert "Dune" in html
        assert "Herbert, Frank" in html
        assert "/library/Herbert/Dune/dune.epub" in html

    def test_renders_tag_and_genre_counts(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        mock_catalog.get_tags_for_book.return_value = ["sci-fi", "classic", "novel"]
        mock_catalog.get_genres_for_book.return_value = [
            ("Science Fiction", True),
            ("Adventure", False),
        ]
        mock_catalog._conn.execute.return_value.fetchone.return_value = (0,)

        html = client.get("/books/1/delete").data.decode()

        assert "3 tags" in html
        assert "2 genres" in html

    def test_renders_size_when_file_present(self, mock_catalog, client, tmp_path):
        epub = tmp_path / "book.epub"
        epub.write_bytes(b"x" * 2048)
        mock_catalog.get_by_id.return_value = make_book(1, output_path=epub)
        mock_catalog._conn.execute.return_value.fetchone.return_value = (0,)

        html = client.get("/books/1/delete").data.decode()

        # 2048 bytes formats as 2.0 KB.
        assert "2.0 KB" in html

    def test_renders_duplicate_cluster_notice(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(
            1, output_path=Path("/library/shared/dune.epub")
        )
        # One other row also points at the same output_path.
        mock_catalog._conn.execute.return_value.fetchone.return_value = (1,)

        html = client.get("/books/1/delete").data.decode()

        assert "1 other catalog" in html or "1 duplicate" in html
        assert "point" in html.lower()

    def test_no_duplicate_notice_when_zero(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        mock_catalog._conn.execute.return_value.fetchone.return_value = (0,)

        html = client.get("/books/1/delete").data.decode()
        assert "duplicate" not in html.lower()

    def test_panel_has_destructive_actions(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        mock_catalog._conn.execute.return_value.fetchone.return_value = (0,)

        html = client.get("/books/1/delete").data.decode()

        assert "btn-destructive" in html
        assert "Delete book + file" in html
        assert "Delete row only" in html
        assert "Cancel" in html

    def test_cancel_swaps_back_to_detail(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        mock_catalog._conn.execute.return_value.fetchone.return_value = (0,)

        html = client.get("/books/1/delete").data.decode()

        # Cancel does an hx-get back to the detail view.
        assert "hx-get" in html
        assert "/books/1" in html

    def test_post_form_targets_delete_route(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        mock_catalog._conn.execute.return_value.fetchone.return_value = (0,)

        html = client.get("/books/1/delete").data.decode()

        # Form posts to /books/1/delete with keep_file selector.
        assert 'action="/books/1/delete"' in html or "hx-post" in html
        assert 'name="keep_file"' in html

    def test_404_when_book_missing(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = None
        response = client.get("/books/999/delete")
        assert response.status_code == 404

    def test_in_dialog_cancel_closes_dialog(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        mock_catalog._conn.execute.return_value.fetchone.return_value = (0,)

        html = client.get("/books/1/delete?in_dialog=1").data.decode()

        # Loaded into the list dialog: Cancel closes it rather than swapping
        # back to a #book-content region that doesn't exist there.
        assert "dialog').close()" in html
        assert "#book-content" not in html


class TestDeleteConfirmFilePathNone:
    def test_renders_when_no_output_path(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, output_path=None)
        mock_catalog._conn.execute.return_value.fetchone.return_value = (0,)

        html = client.get("/books/1/delete").data.decode()
        # No crash; renders with (no file) marker or similar.
        assert "Delete this book?" in html


class TestDeletePost:
    def test_keep_file_removes_row_flashes_success(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune", authors=["Herbert"])
        with patch("bookery.web.routes.remove_book") as mock_remove:
            mock_remove.return_value = _build_result(
                title="Dune",
                author="Herbert",
                file_path=Path("/library/dune.epub"),
                file_removed=False,
            )
            response = client.post("/books/1/delete", data={"keep_file": "1"})

        # remove_book invoked with keep_file=True
        mock_remove.assert_called_once()
        _, kwargs = mock_remove.call_args
        assert kwargs["keep_file"] is True

        assert response.headers.get("HX-Redirect") == "/books"

        # Flash carried into session, visible on /books.
        landing = client.get("/books").data.decode()
        assert "Removed" in landing
        assert "Dune" in landing

    def test_delete_book_and_file_removes_everything(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune", authors=["Herbert"])
        with patch("bookery.web.routes.remove_book") as mock_remove:
            mock_remove.return_value = _build_result(
                title="Dune",
                author="Herbert",
                file_path=Path("/library/dune.epub"),
                file_removed=True,
                siblings_removed=(Path("/library/dune.kepub.epub"),),
            )
            response = client.post("/books/1/delete", data={"keep_file": "0"})

        _, kwargs = mock_remove.call_args
        assert kwargs["keep_file"] is False

        assert response.headers.get("HX-Redirect") == "/books"
        landing = client.get("/books").data.decode()
        assert "Removed" in landing

    def test_missing_file_surfaces_warning_flash(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune", authors=["Herbert"])
        with patch("bookery.web.routes.remove_book") as mock_remove:
            mock_remove.return_value = _build_result(
                title="Dune",
                author="Herbert",
                file_path=Path("/library/dune.epub"),
                file_removed=False,
                warnings=("file already missing: /library/dune.epub",),
            )
            response = client.post("/books/1/delete", data={"keep_file": "0"})

        assert response.headers.get("HX-Redirect") == "/books"
        landing = client.get("/books").data.decode()
        # Warning category renders with a recognizable class/marker.
        assert "warning" in landing.lower()
        assert "already missing" in landing

    def test_duplicate_cluster_keeps_file_with_warning(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune", authors=["Herbert"])
        warning = "1 other catalog entries point at this file; keeping /library/dune.epub on disk."
        with patch("bookery.web.routes.remove_book") as mock_remove:
            mock_remove.return_value = _build_result(
                title="Dune",
                author="Herbert",
                file_path=Path("/library/dune.epub"),
                file_removed=False,
                warnings=(warning,),
            )
            response = client.post("/books/1/delete", data={"keep_file": "0"})

        assert response.headers.get("HX-Redirect") == "/books"
        landing = client.get("/books").data.decode()
        assert "warning" in landing.lower()
        assert "other catalog entries point at this file" in landing

    def test_post_404_when_book_missing(self, mock_catalog, client):
        # remove_book raises ValueError when ID is unknown; mock get_by_id None
        # so the route can short-circuit with 404.
        mock_catalog.get_by_id.return_value = None
        response = client.post("/books/999/delete", data={"keep_file": "0"})
        assert response.status_code == 404


class TestDetailToolbarDeleteButtonActive:
    def test_delete_button_wires_to_confirm_route(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1").data.decode()
        # The Delete button is no longer disabled — it hx-gets the confirm route.
        assert "/books/1/delete" in html
        assert 'title="Coming soon"' not in html

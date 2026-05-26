# ABOUTME: End-to-end tests for the `bookery serve` web UI command.
# ABOUTME: Verifies CLI help, missing DB error, and full browse-search-detail flow.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata
from bookery.web import create_app


class TestWebE2E:
    """End-to-end tests for the serve command and web UI."""

    def test_help_shows_serve_command(self) -> None:
        """bookery serve --help shows command documentation."""
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "Launch the web UI" in result.output

    def test_no_db_gives_clean_error(self, tmp_path) -> None:
        """bookery serve with no DB gives a user-friendly error."""
        nonexistent = tmp_path / "missing" / "library.db"
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--db", str(nonexistent)])
        assert result.exit_code != 0
        assert "No library found" in result.output
        assert "Traceback" not in result.output

    def test_full_browse_search_detail_flow(self, tmp_path) -> None:
        """Full user journey: browse list, search, view detail."""
        db_path = tmp_path / "library.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        catalog.add_book(
            BookMetadata(
                title="Neuromancer",
                authors=["Gibson, William"],
                author_sort="Gibson, William",
                isbn="9780441569595",
                language="en",
                publisher="Ace Books",
                description="Cyberpunk noir.",
                source_path=Path("/books/neuromancer.epub"),
            ),
            file_hash="hash_neuro",
        )
        catalog.add_book(
            BookMetadata(
                title="Snow Crash",
                authors=["Stephenson, Neal"],
                author_sort="Stephenson, Neal",
                isbn="9780553380958",
                language="en",
                publisher="Bantam",
                description="A pizza delivery driver saves the world.",
                source_path=Path("/books/snowcrash.epub"),
            ),
            file_hash="hash_snow",
        )

        app = create_app(catalog)
        app.config["TESTING"] = True
        client = app.test_client()

        # Step 1: Browse — both books visible, sorted by author
        response = client.get("/books")
        html = response.data.decode()
        assert response.status_code == 200
        assert "Neuromancer" in html
        assert "Snow Crash" in html
        assert html.index("Gibson, William") < html.index("Stephenson, Neal")

        # Step 2: Search — only matching book
        response = client.get("/books?q=cyberpunk")
        html = response.data.decode()
        assert "Neuromancer" in html
        assert "Snow Crash" not in html

        # Step 3: Detail — full metadata
        response = client.get("/books/1")
        html = response.data.decode()
        assert "Neuromancer" in html
        assert "Gibson, William" in html
        assert "Cyberpunk noir." in html
        assert "9780441569595" in html

        # Step 4: htmx partial — no full page wrapper
        response = client.get("/books?q=snow", headers={"HX-Request": "true"})
        html = response.data.decode()
        assert "Snow Crash" in html
        assert "<html" not in html

        conn.close()

    def test_full_edit_flow(self, tmp_path) -> None:
        """Full user journey: browse → detail → edit → save → verify."""
        db_path = tmp_path / "library.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        catalog.add_book(
            BookMetadata(
                title="Neuromancer",
                authors=["Gibson, William"],
                author_sort="Gibson, William",
                isbn="9780441569595",
                language="en",
                publisher="Ace Books",
                description="Cyberpunk noir.",
                source_path=Path("/books/neuromancer.epub"),
            ),
            file_hash="hash_neuro",
        )

        app = create_app(catalog)
        app.config["TESTING"] = True
        client = app.test_client()

        # Step 1: Browse and find the book
        response = client.get("/books")
        assert "Neuromancer" in response.data.decode()

        # Step 2: View detail
        response = client.get("/books/1")
        html = response.data.decode()
        assert "Neuromancer" in html
        assert "Edit" in html

        # Step 3: Get edit form
        response = client.get("/books/1/edit")
        html = response.data.decode()
        assert "<form" in html
        assert "Neuromancer" in html

        # Step 4: Save with updated metadata
        response = client.post(
            "/books/1/edit",
            data={
                "title": "Neuromancer (Revised)",
                "authors": "Gibson, William; Sterling, Bruce",
                "isbn": "9780441569595",
                "language": "en",
                "publisher": "Ace Books",
                "description": "Cyberpunk noir, updated edition.",
                "series": "Sprawl Trilogy",
                "series_index": "1",
            },
        )
        assert response.status_code == 200
        html = response.data.decode()
        assert "Neuromancer (Revised)" in html

        # Step 5: Verify detail page shows updated data
        response = client.get("/books/1")
        html = response.data.decode()
        assert "Neuromancer (Revised)" in html
        assert "Gibson, William" in html
        assert "Sterling, Bruce" in html
        assert "Sprawl Trilogy" in html
        assert "Cyberpunk noir, updated edition." in html

        conn.close()

    def test_bulk_mark_finished_round_trip(self, tmp_path) -> None:
        """P3 (#183): select 5 books on the list, bulk-mark Finished, verify
        each row renders the Finished chip on re-fetch.
        """
        db_path = tmp_path / "library.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        ids: list[int] = []
        for i in range(5):
            bid = catalog.add_book(
                BookMetadata(
                    title=f"Book {i}",
                    authors=[f"Author {i}"],
                    author_sort=f"Author {i}",
                    source_path=Path(f"/books/b{i}.epub"),
                ),
                file_hash=f"hash{i}".ljust(64, "0"),
            )
            ids.append(bid)

        app = create_app(catalog)
        app.config["TESTING"] = True
        client = app.test_client()

        # Step 1: List page renders the bulk form + checkboxes.
        response = client.get("/books")
        html = response.data.decode()
        assert 'id="bulk-status-form"' in html
        for bid in ids:
            assert f'value="{bid}"' in html

        # Step 2: Submit the bulk-mark. Werkzeug's test client encodes a list
        # value into repeated form fields, which is what request.form.getlist
        # picks up server-side.
        response = client.post(
            "/books/bulk-status",
            data={"ids": [str(bid) for bid in ids], "status": "finished"},
        )
        assert response.status_code == 200

        # Step 3: Re-fetch the list — all five rows should now carry the
        # Finished chip class.
        response = client.get("/books")
        html = response.data.decode()
        assert html.count("status-finished") >= 5

        # Step 4: Filter by ?status=finished and confirm all five appear.
        response = client.get("/books?status=finished")
        html = response.data.decode()
        for i in range(5):
            assert f"Book {i}" in html

        # Step 5: Toggle one back to Reading via the single-book route and
        # confirm the detail-reading partial reflects the new state.
        response = client.post(f"/books/{ids[0]}/status", data={"status": "reading"})
        assert response.status_code == 200
        html = response.data.decode()
        assert 'aria-pressed="true"' in html
        assert "Reading" in html

        # Filter by ?status=reading — only that one shows up.
        response = client.get("/books?status=reading")
        html = response.data.decode()
        assert "Book 0" in html
        # The four still-finished books are filtered out.
        for i in range(1, 5):
            assert f"Book {i}" not in html

        conn.close()

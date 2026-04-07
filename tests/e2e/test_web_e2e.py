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

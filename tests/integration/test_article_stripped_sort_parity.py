# ABOUTME: Integration test asserting /books and `bookery ls` agree on ordering.
# ABOUTME: Both surfaces must return book titles in the same article-stripped order.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata
from bookery.web import create_app

# Canonical fixture from issue #192's acceptance criteria. Authors are chosen
# so the author_sort ASC order coincides with the article-stripped title
# order, which keeps the test discriminating for both primary (author) and
# secondary (title) sort keys without taking a stance on the order users
# expect from real Tolkien/Le Guin/Dreiser/Herbert rows.
FIXTURE: list[tuple[str, str]] = [
    ("The Hobbit", "Cooper, Carol"),
    ("A Wizard of Earthsea", "Davis, Don"),
    ("An American Tragedy", "Adams, Alice"),
    ("Dune", "Brown, Bob"),
]

# Article-stripped order: American < Dune < Hobbit < Wizard.
EXPECTED_ORDER: list[str] = [
    "An American Tragedy",
    "Dune",
    "The Hobbit",
    "A Wizard of Earthsea",
]


def _seed_catalog(db_path: Path) -> None:
    """Populate a fresh SQLite library with the issue #192 fixture."""
    conn = open_library(db_path)
    try:
        catalog = LibraryCatalog(conn)
        for title, author in FIXTURE:
            meta = BookMetadata(
                title=title,
                authors=[author],
                author_sort=author,
                source_path=Path(f"/tmp/{title}.epub"),
            )
            catalog.add_book(meta, file_hash=(title * 8).ljust(64, "0"))
    finally:
        conn.close()


def _positions(haystack: str, needles: list[str]) -> list[int]:
    """Return the first index of each ``needle`` inside ``haystack``.

    Raises ``AssertionError`` if any title is missing so a regression that
    drops a row surfaces here instead of silently producing a partial order.
    """
    positions: list[int] = []
    for needle in needles:
        idx = haystack.find(needle)
        assert idx >= 0, f"title {needle!r} not found in output"
        positions.append(idx)
    return positions


def _titles_in_order(haystack: str, candidates: list[str]) -> list[str]:
    """Return ``candidates`` re-ordered by their first appearance in ``haystack``."""
    positions = _positions(haystack, candidates)
    pairs = sorted(zip(positions, candidates, strict=True))
    return [title for _, title in pairs]


def test_cli_ls_and_web_books_share_article_stripped_order(tmp_path: Path) -> None:
    """The CLI and web surfaces must report the same article-stripped order.

    Seed a real catalog, call `bookery ls --db ...` via the Click runner, and
    fetch `/books` through the Flask test client backed by the same DB. The
    relative order of the four fixture titles must match — and must match the
    article-stripped expected order — across both surfaces.
    """
    db_path = tmp_path / "parity.db"
    _seed_catalog(db_path)

    # CLI surface — `bookery ls`. Rich-rendered table output; the assertion
    # is on the relative order of title substrings, which is insensitive to
    # column widths or terminal wrapping.
    runner = CliRunner()
    result = runner.invoke(cli, ["ls", "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    cli_titles = _titles_in_order(result.output, [t for t, _ in FIXTURE])

    # Web surface — /books. Flask test client renders the same Jinja list
    # template that real browsers see; titles appear as text within anchor
    # tags so the relative-position check works on the raw HTML body.
    conn = open_library(db_path)
    try:
        app = create_app(LibraryCatalog(conn))
        app.config["TESTING"] = True
        client = app.test_client()
        response = client.get("/books")
        assert response.status_code == 200, response.data
        body = response.data.decode("utf-8")
    finally:
        conn.close()

    web_titles = _titles_in_order(body, [t for t, _ in FIXTURE])

    # Both surfaces ship the canonical article-stripped order, and they agree.
    assert cli_titles == EXPECTED_ORDER
    assert web_titles == EXPECTED_ORDER
    assert cli_titles == web_titles

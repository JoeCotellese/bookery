# ABOUTME: Integration tests for the #303 title-correspondence gate on series backfill.
# ABOUTME: A threshold-clearing candidate for a different book must not donate its series.

from pathlib import Path
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata


class StubProvider:
    """Returns canned candidates and records which lookup path was taken."""

    def __init__(
        self,
        *,
        by_isbn: list[MetadataCandidate] | None = None,
        by_title: list[MetadataCandidate] | None = None,
    ) -> None:
        self._by_isbn = by_isbn or []
        self._by_title = by_title or []
        self.isbn_calls: list[str] = []
        self.title_calls: list[tuple[str, str | None]] = []

    def search_by_isbn(self, isbn: str) -> list[MetadataCandidate]:
        self.isbn_calls.append(isbn)
        return list(self._by_isbn)

    def search_by_title_author(self, title: str, author: str | None) -> list[MetadataCandidate]:
        self.title_calls.append((title, author))
        return list(self._by_title)


def _candidate(
    title: str,
    *,
    series: str | None = None,
    series_index: float | None = None,
    confidence: float = 0.9,
    isbn: str | None = None,
) -> MetadataCandidate:
    return MetadataCandidate(
        metadata=BookMetadata(
            title=title,
            authors=["Some Author"],
            isbn=isbn,
            series=series,
            series_index=series_index,
        ),
        confidence=confidence,
        source="hardcover",
        source_id="stub-1",
    )


def _add_book(
    db_path: Path,
    title: str,
    *,
    isbn: str | None = None,
    authors: list[str] | None = None,
) -> int:
    conn = open_library(db_path)
    book_id = LibraryCatalog(conn).add_book(
        BookMetadata(
            title=title,
            authors=authors or ["Some Author"],
            isbn=isbn,
            source_path=Path(f"/books/{title}.epub"),
        ),
        file_hash=f"hash-{title}",
    )
    conn.close()
    return book_id


def _row(db_path: Path, book_id: int) -> dict[str, Any]:
    conn = open_library(db_path)
    row = conn.execute(
        "SELECT series, series_index FROM books WHERE id = ?", (book_id,)
    ).fetchone()
    conn.close()
    return {"series": row["series"], "series_index": row["series_index"]}


def _run_backfill(db_path: Path, provider: Any, *args: str) -> Any:
    with patch(
        "bookery.cli.commands.series_cmd._create_provider",
        return_value=provider,
    ):
        return CliRunner().invoke(cli, ["series", "backfill", *args, "--db", str(db_path)])


class TestUnrelatedCandidateRejected:
    """The founding Pattern A symptom: series metadata about a different book."""

    def test_high_confidence_unrelated_candidate_donates_nothing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "Book 17 - Force Heretic I - Remnant")
        provider = StubProvider(
            by_title=[
                _candidate(
                    "Expeditionary Force: Match Game",
                    series="Expeditionary Force",
                    series_index=17.0,
                    confidence=0.95,
                )
            ]
        )

        result = _run_backfill(db_path, provider, str(book_id))

        assert result.exit_code == 0
        assert _row(db_path, book_id) == {"series": None, "series_index": None}

    def test_rejection_reason_is_shown_to_the_user(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "Book 5 - Trapped")
        provider = StubProvider(
            by_title=[
                _candidate(
                    "Aquilon: The Water Mage",
                    series="Aquilon: The Water Mage",
                    series_index=5.0,
                )
            ]
        )

        result = _run_backfill(db_path, provider, str(book_id))

        assert result.exit_code == 0
        assert "does not correspond" in result.output

    def test_a_corresponding_candidate_later_in_the_list_still_wins(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "The Way of Kings")
        provider = StubProvider(
            by_title=[
                _candidate("Valkyrie: Jane Foster", series="Valkyrie", series_index=2.0),
                _candidate(
                    "The Way of Kings",
                    series="The Stormlight Archive",
                    series_index=1.0,
                ),
            ]
        )

        result = _run_backfill(db_path, provider, str(book_id))

        assert result.exit_code == 0
        assert _row(db_path, book_id) == {"series": "The Stormlight Archive", "series_index": 1.0}


class TestBookNumberPrefixIndex:
    def test_index_echoing_the_book_n_prefix_is_not_inherited(self, tmp_path: Path) -> None:
        """Title corresponds, but the position only agrees with our own filename."""
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "Book 3 - Force Heretic I - Remnant")
        provider = StubProvider(
            by_title=[
                _candidate(
                    "Force Heretic I: Remnant",
                    series="The New Jedi Order",
                    series_index=3.0,
                )
            ]
        )

        result = _run_backfill(db_path, provider, str(book_id))

        assert result.exit_code == 0
        assert _row(db_path, book_id) == {"series": "The New Jedi Order", "series_index": None}

    def test_an_index_that_disagrees_with_the_prefix_is_kept(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "Book 3 - Force Heretic I - Remnant")
        provider = StubProvider(
            by_title=[
                _candidate(
                    "Force Heretic I: Remnant",
                    series="The New Jedi Order",
                    series_index=15.0,
                )
            ]
        )

        result = _run_backfill(db_path, provider, str(book_id))

        assert result.exit_code == 0
        assert _row(db_path, book_id) == {"series": "The New Jedi Order", "series_index": 15.0}


class TestIsbnPathUnaffected:
    def test_isbn_match_keeps_its_series_and_index_without_title_correspondence(
        self, tmp_path: Path
    ) -> None:
        """ISBN settles identity, so a differently-worded provider title is fine."""
        db_path = tmp_path / "test.db"
        isbn = "9780312850098"
        book_id = _add_book(db_path, "eotw_unabridged_v3", isbn=isbn)
        provider = StubProvider(
            by_isbn=[
                _candidate(
                    "The Eye of the World",
                    series="The Wheel of Time",
                    series_index=1.0,
                    isbn=isbn,
                )
            ]
        )

        result = _run_backfill(db_path, provider, str(book_id))

        assert result.exit_code == 0
        assert _row(db_path, book_id) == {"series": "The Wheel of Time", "series_index": 1.0}
        assert provider.title_calls == []

    def test_isbn_miss_falls_back_to_title_search_and_is_gated(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "Book 1 - Target", isbn="9780312850098")
        provider = StubProvider(
            by_isbn=[],
            by_title=[
                _candidate(
                    "The Book of Biff: Volume One", series="The Book of Biff", series_index=1.0
                )
            ],
        )

        result = _run_backfill(db_path, provider, str(book_id))

        assert result.exit_code == 0
        assert provider.title_calls  # fallback really ran
        assert _row(db_path, book_id) == {"series": None, "series_index": None}


class TestLegitimateOneBookSeriesSurvive:
    """The #301 do-not-clean list must still be accepted on a fresh backfill."""

    def test_real_one_book_series_are_accepted(self, tmp_path: Path) -> None:
        cases = [
            ("Raising Steam", "Raising Steam: A Discworld Novel", "Discworld", 34.0),
            ("Festive in Death", "Festive in Death", "In Death", 14.0),
            ("Trojan Odyssey", "Trojan Odyssey", "Dirk Pitt", 23.0),
            ("The Way of Kings", "The Way of Kings", "The Stormlight Archive", 1.0),
            # No index at all — a missing position must never be a reject.
            ("To Sleep in a Sea of Stars", "To Sleep in a Sea of Stars", "Fractalverse", None),
            ("Dungeon Crawler Carl", "Dungeon Crawler Carl", "Dungeon Crawler Carl", None),
            ("Ancestral Night", "Ancestral Night", "Hierarchy", None),
            (
                "The Three-Body Problem",
                "The Three-Body Problem",
                "Remembrance of Earth's Past",
                1.0,
            ),
        ]
        for local_title, provider_title, series, index in cases:
            db_path = tmp_path / f"{series}.db"
            book_id = _add_book(db_path, local_title)
            provider = StubProvider(
                by_title=[_candidate(provider_title, series=series, series_index=index)]
            )

            result = _run_backfill(db_path, provider, str(book_id))

            assert result.exit_code == 0, f"{series}: {result.output}"
            assert _row(db_path, book_id) == {
                "series": series,
                "series_index": index,
            }, f"{series} was not accepted"


class TestHeuristicFallbackStillRuns:
    def test_rejected_candidate_falls_through_to_the_title_heuristic(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        book_id = _add_book(db_path, "Silverthorn (Riftwar Saga #2)")
        provider = StubProvider(
            by_title=[_candidate("Valkyrie: Jane Foster", series="Valkyrie", series_index=2.0)]
        )

        result = _run_backfill(db_path, provider, str(book_id))

        assert result.exit_code == 0
        assert _row(db_path, book_id) == {"series": "Riftwar Saga", "series_index": 2.0}

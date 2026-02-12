# ABOUTME: Unit tests for the interactive review flow.
# ABOUTME: Tests candidate display, user selection, quiet mode auto-accept, and skip behavior.

from io import StringIO
from unittest.mock import patch

from rich.console import Console

from bookery.cli.review import ReviewSession
from bookery.metadata import BookMetadata
from bookery.metadata.candidate import MetadataCandidate


def _make_candidate(
    title: str,
    author: str,
    confidence: float,
    *,
    isbn: str | None = None,
    language: str | None = None,
    publisher: str | None = None,
    description: str | None = None,
) -> MetadataCandidate:
    """Helper to create a MetadataCandidate with optional metadata fields."""
    return MetadataCandidate(
        metadata=BookMetadata(
            title=title,
            authors=[author],
            isbn=isbn,
            language=language,
            publisher=publisher,
            description=description,
        ),
        confidence=confidence,
        source="test",
        source_id=f"test-{title}",
    )


class TestReviewSession:
    """Tests for ReviewSession interactive flow."""

    def test_user_selects_candidate(self) -> None:
        """User entering '1' selects the first candidate."""
        extracted = BookMetadata(title="Old Title")
        candidates = [
            _make_candidate("New Title", "Author A", 0.9),
            _make_candidate("Alt Title", "Author B", 0.7),
        ]
        console = Console(file=StringIO())
        session = ReviewSession(console=console)

        with patch("bookery.cli.review.click.prompt", return_value="1"):
            result = session.review(extracted, candidates)

        assert result is not None
        assert result.title == "New Title"

    def test_user_selects_second_candidate(self) -> None:
        """User entering '2' selects the second candidate."""
        extracted = BookMetadata(title="Old Title")
        candidates = [
            _make_candidate("First", "Author A", 0.9),
            _make_candidate("Second", "Author B", 0.7),
        ]
        console = Console(file=StringIO())
        session = ReviewSession(console=console)

        with patch("bookery.cli.review.click.prompt", return_value="2"):
            result = session.review(extracted, candidates)

        assert result is not None
        assert result.title == "Second"

    def test_user_skips(self) -> None:
        """User entering 's' returns None (skip)."""
        extracted = BookMetadata(title="Old Title")
        candidates = [_make_candidate("New Title", "Author A", 0.9)]
        console = Console(file=StringIO())
        session = ReviewSession(console=console)

        with patch("bookery.cli.review.click.prompt", return_value="s"):
            result = session.review(extracted, candidates)

        assert result is None

    def test_user_keeps_original(self) -> None:
        """User entering 'k' returns the extracted metadata (keep original)."""
        extracted = BookMetadata(title="Original Title", authors=["Original Author"])
        candidates = [_make_candidate("New Title", "Author A", 0.9)]
        console = Console(file=StringIO())
        session = ReviewSession(console=console)

        with patch("bookery.cli.review.click.prompt", return_value="k"):
            result = session.review(extracted, candidates)

        assert result is not None
        assert result.title == "Original Title"

    def test_quiet_mode_auto_accepts_high_confidence(self) -> None:
        """In quiet mode, candidates above threshold are auto-accepted."""
        extracted = BookMetadata(title="Old Title")
        candidates = [_make_candidate("Best Match", "Author A", 0.9)]
        console = Console(file=StringIO())
        session = ReviewSession(console=console, quiet=True, threshold=0.8)

        result = session.review(extracted, candidates)

        assert result is not None
        assert result.title == "Best Match"

    def test_quiet_mode_skips_low_confidence(self) -> None:
        """In quiet mode, candidates below threshold are skipped."""
        extracted = BookMetadata(title="Old Title")
        candidates = [_make_candidate("Weak Match", "Author A", 0.5)]
        console = Console(file=StringIO())
        session = ReviewSession(console=console, quiet=True, threshold=0.8)

        result = session.review(extracted, candidates)

        assert result is None


class TestDetailView:
    """Tests for the detail view (v<N>) flow."""

    def test_view_detail_then_accept(self) -> None:
        """User enters v1 to view details, then a to accept that candidate."""
        extracted = BookMetadata(title="Old Title")
        candidates = [
            _make_candidate(
                "The Templar Legacy",
                "Steve Berry",
                0.7,
                isbn="9780345504500",
                language="en",
                publisher="Ballantine",
                description="Cotton Malone investigates.",
            ),
        ]
        console = Console(file=StringIO())
        session = ReviewSession(console=console)

        with patch(
            "bookery.cli.review.click.prompt", side_effect=["v1", "a"]
        ):
            result = session.review(extracted, candidates)

        assert result is not None
        assert result.title == "The Templar Legacy"
        assert result.isbn == "9780345504500"

    def test_view_detail_then_back_and_select(self) -> None:
        """User views details, goes back to list, then selects a candidate."""
        extracted = BookMetadata(title="Old Title")
        candidates = [
            _make_candidate("First", "Author A", 0.9, isbn="111"),
            _make_candidate("Second", "Author B", 0.7, isbn="222"),
        ]
        console = Console(file=StringIO())
        session = ReviewSession(console=console)

        with patch(
            "bookery.cli.review.click.prompt", side_effect=["v1", "b", "1"]
        ):
            result = session.review(extracted, candidates)

        assert result is not None
        assert result.title == "First"

    def test_view_detail_then_back_and_skip(self) -> None:
        """User views details, goes back to list, then skips."""
        extracted = BookMetadata(title="Old Title")
        candidates = [
            _make_candidate("First", "Author A", 0.9),
        ]
        console = Console(file=StringIO())
        session = ReviewSession(console=console)

        with patch(
            "bookery.cli.review.click.prompt", side_effect=["v1", "b", "s"]
        ):
            result = session.review(extracted, candidates)

        assert result is None

    def test_view_detail_shows_metadata_fields(self) -> None:
        """Detail view output contains ISBN, publisher, and description."""
        extracted = BookMetadata(
            title="Old Title",
            authors=["Unknown"],
            isbn=None,
            publisher=None,
        )
        candidates = [
            _make_candidate(
                "The Templar Legacy",
                "Steve Berry",
                0.7,
                isbn="9780345504500",
                language="en",
                publisher="Ballantine",
                description="Cotton Malone investigates.",
            ),
        ]
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        session = ReviewSession(console=console)

        with patch(
            "bookery.cli.review.click.prompt", side_effect=["v1", "a"]
        ):
            session.review(extracted, candidates)

        rendered = output.getvalue()
        assert "9780345504500" in rendered
        assert "Ballantine" in rendered
        assert "Cotton Malone investigates." in rendered

    def test_view_invalid_number_reprompts(self) -> None:
        """v99 with only 2 candidates re-shows the prompt."""
        extracted = BookMetadata(title="Old Title")
        candidates = [
            _make_candidate("First", "Author A", 0.9),
            _make_candidate("Second", "Author B", 0.7),
        ]
        console = Console(file=StringIO())
        session = ReviewSession(console=console)

        with patch(
            "bookery.cli.review.click.prompt", side_effect=["v99", "s"]
        ):
            result = session.review(extracted, candidates)

        assert result is None


class TestUrlLookup:
    """Tests for the [u] URL lookup option in review flow."""

    def test_url_lookup_then_accept(self) -> None:
        """User enters u, pastes URL, lookup returns candidate, user accepts."""
        extracted = BookMetadata(title="Old Title")
        candidates = [_make_candidate("First", "Author A", 0.9)]
        url_candidate = _make_candidate(
            "From URL", "URL Author", 1.0, isbn="9780000000001"
        )

        def fake_lookup(url: str) -> MetadataCandidate | None:
            return url_candidate

        console = Console(file=StringIO())
        session = ReviewSession(console=console, lookup_fn=fake_lookup)

        with patch(
            "bookery.cli.review.click.prompt",
            side_effect=["u", "https://openlibrary.org/works/OL123W", "a"],
        ):
            result = session.review(extracted, candidates)

        assert result is not None
        assert result.title == "From URL"
        assert result.isbn == "9780000000001"

    def test_url_lookup_failure_reprompts(self) -> None:
        """lookup_fn returns None, user gets error message, re-prompted."""
        extracted = BookMetadata(title="Old Title")
        candidates = [_make_candidate("First", "Author A", 0.9)]

        def failing_lookup(url: str) -> MetadataCandidate | None:
            return None

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        session = ReviewSession(console=console, lookup_fn=failing_lookup)

        with patch(
            "bookery.cli.review.click.prompt",
            side_effect=["u", "https://openlibrary.org/works/bad", "s"],
        ):
            result = session.review(extracted, candidates)

        assert result is None
        rendered = output.getvalue()
        assert "Could not fetch" in rendered

    def test_url_option_hidden_without_lookup_fn(self) -> None:
        """[u] option is not shown when no lookup_fn is provided."""
        extracted = BookMetadata(title="Old Title")
        candidates = [_make_candidate("First", "Author A", 0.9)]
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        session = ReviewSession(console=console)

        with patch(
            "bookery.cli.review.click.prompt", return_value="s"
        ) as mock_prompt:
            session.review(extracted, candidates)

        # The prompt text should NOT contain [u]
        prompt_text = mock_prompt.call_args[0][0]
        assert "[u]" not in prompt_text

    def test_url_option_shown_with_lookup_fn(self) -> None:
        """[u] option IS shown when lookup_fn is provided."""
        extracted = BookMetadata(title="Old Title")
        candidates = [_make_candidate("First", "Author A", 0.9)]

        def dummy_lookup(url: str) -> MetadataCandidate | None:
            return None

        console = Console(file=StringIO())
        session = ReviewSession(console=console, lookup_fn=dummy_lookup)

        with patch(
            "bookery.cli.review.click.prompt", return_value="s"
        ) as mock_prompt:
            session.review(extracted, candidates)

        prompt_text = mock_prompt.call_args[0][0]
        assert "[u]" in prompt_text

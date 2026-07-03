# ABOUTME: Unit tests for fetch_covers threading through build_match_fn (issue #285).
# ABOUTME: Verifies the add-command match callback forwards the flag to match_one.

from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console

from bookery.cli._match_helpers import build_match_fn
from bookery.core.pipeline import MatchOneResult
from bookery.metadata.types import BookMetadata


class TestBuildMatchFnCovers:
    def _invoke(self, tmp_path: Path, **build_kwargs: bool) -> MagicMock:
        """Build a match_fn and call it once; return the match_one mock."""
        with (
            patch("bookery.cli._match_helpers.build_metadata_provider"),
            patch("bookery.core.pipeline.match_one") as mock_match_one,
        ):
            mock_match_one.return_value = MatchOneResult(status="skipped")
            match_fn = build_match_fn(
                Console(quiet=True),
                tmp_path,
                quiet=True,
                threshold=0.8,
                **build_kwargs,
            )
            match_fn(BookMetadata(title="X"), tmp_path / "x.epub")
        return mock_match_one

    def test_default_fetches_covers(self, tmp_path: Path) -> None:
        mock_match_one = self._invoke(tmp_path)
        assert mock_match_one.call_args.kwargs.get("fetch_covers") is True

    def test_no_covers_threaded_through(self, tmp_path: Path) -> None:
        mock_match_one = self._invoke(tmp_path, fetch_covers=False)
        assert mock_match_one.call_args.kwargs.get("fetch_covers") is False

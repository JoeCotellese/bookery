# ABOUTME: End-to-end tests for the bookery match CLI command.
# ABOUTME: Tests the full match pipeline using CliRunner with fake providers.

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli
from bookery.formats.epub import read_epub_metadata
from bookery.metadata import BookMetadata
from bookery.metadata.candidate import MetadataCandidate


def _make_candidate(
    title: str, author: str, confidence: float, isbn: str | None = None
) -> MetadataCandidate:
    return MetadataCandidate(
        metadata=BookMetadata(title=title, authors=[author], isbn=isbn, language="en"),
        confidence=confidence,
        source="openlibrary",
        source_id=f"test-{title}",
    )


@pytest.fixture
def mangled_epub(tmp_path: Path) -> Path:
    """Create an EPUB with a mangled CamelCase title and no author."""
    book = epub.EpubBook()
    book.set_identifier("mangled-test-id")
    book.set_title("SteveBerry-TheTemplarLegacy")
    book.set_language("en")

    chapter = epub.EpubHtml(title="Chapter 1", file_name="chap01.xhtml", lang="en")
    chapter.content = b"<html><body><h1>Chapter 1</h1><p>Content.</p></body></html>"
    book.add_item(chapter)

    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    filepath = tmp_path / "mangled_title.epub"
    epub.write_epub(str(filepath), book)
    return filepath


class TestMatchCliEndToEnd:
    """End-to-end tests for bookery match command."""

    def test_quiet_match_writes_updated_epub(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """Quiet match writes a copy with updated metadata."""
        output_dir = tmp_path / "output"
        candidate = _make_candidate("Il Nome della Rosa", "Umberto Eco", 0.95)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(sample_epub), "-q", "-o", str(output_dir)],
            )

        assert result.exit_code == 0
        outputs = list(output_dir.glob("*.epub"))
        assert len(outputs) == 1
        meta = read_epub_metadata(outputs[0])
        assert meta.title == "Il Nome della Rosa"

    def test_original_file_preserved(self, sample_epub: Path, tmp_path: Path) -> None:
        """Original EPUB is byte-identical after match pipeline."""
        original_bytes = sample_epub.read_bytes()
        output_dir = tmp_path / "output"
        candidate = _make_candidate("Changed", "Author", 0.95)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            runner.invoke(
                cli,
                ["match", str(sample_epub), "-q", "-o", str(output_dir)],
            )

        assert sample_epub.read_bytes() == original_bytes

    def test_match_directory_processes_all(
        self, sample_epub: Path, minimal_epub: Path, tmp_path: Path
    ) -> None:
        """Match processes all EPUB files in a directory."""
        scan_dir = tmp_path / "books"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "rose.epub")
        shutil.copy(minimal_epub, scan_dir / "minimal.epub")
        output_dir = tmp_path / "output"
        candidate = _make_candidate("Found", "Author", 0.9)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = [candidate]
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(scan_dir), "-q", "-o", str(output_dir)],
            )

        assert result.exit_code == 0
        outputs = list(output_dir.glob("*.epub"))
        assert len(outputs) == 2

    def test_summary_shows_counts(self, sample_epub: Path, tmp_path: Path) -> None:
        """Match shows summary with matched/skipped/error counts."""
        output_dir = tmp_path / "output"
        candidate = _make_candidate("Match", "Author", 0.95)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(sample_epub), "-q", "-o", str(output_dir)],
            )

        assert result.exit_code == 0
        assert "matched" in result.output

    def test_match_error_handling(self, corrupt_epub: Path, tmp_path: Path) -> None:
        """Match handles corrupt EPUB files without crashing."""
        output_dir = tmp_path / "output"

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_fn.return_value = MagicMock()

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(corrupt_epub), "-q", "-o", str(output_dir)],
            )

        assert result.exit_code == 0
        assert "1 error" in result.output

    def test_interactive_match_with_input(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """Interactive match accepts user input to select a candidate."""
        output_dir = tmp_path / "output"
        candidate = _make_candidate("Selected Title", "Author", 0.85)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(sample_epub), "-o", str(output_dir)],
                input="1\n",
            )

        assert result.exit_code == 0
        outputs = list(output_dir.glob("*.epub"))
        assert len(outputs) == 1

    def test_match_normalizes_mangled_title(
        self, mangled_epub: Path, tmp_path: Path
    ) -> None:
        """Provider receives normalized (not mangled) title for search."""
        output_dir = tmp_path / "output"
        candidate = _make_candidate("The Templar Legacy", "Steve Berry", 0.95)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(mangled_epub), "-q", "-o", str(output_dir)],
            )

        assert result.exit_code == 0

        # Verify the provider was called with normalized title, not the mangled one
        call_args = mock_provider.search_by_title_author.call_args
        title_arg = call_args[0][0]
        assert "SteveBerry" not in title_arg
        assert " " in title_arg

    def test_interactive_match_shows_normalization_info(
        self, mangled_epub: Path, tmp_path: Path
    ) -> None:
        """Interactive mode shows normalization info for mangled titles."""
        output_dir = tmp_path / "output"
        candidate = _make_candidate("The Templar Legacy", "Steve Berry", 0.95)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(mangled_epub), "-o", str(output_dir)],
                input="1\n",
            )

        assert result.exit_code == 0
        assert "Normalized title" in result.output
        assert "Detected author" in result.output

    def test_interactive_view_detail_and_accept(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """Interactive match: view detail then accept writes updated EPUB."""
        output_dir = tmp_path / "output"
        candidate = _make_candidate(
            "Il Nome della Rosa", "Umberto Eco", 0.85, isbn="9780151446476"
        )

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(sample_epub), "-o", str(output_dir)],
                input="v1\na\n",
            )

        assert result.exit_code == 0
        outputs = list(output_dir.glob("*.epub"))
        assert len(outputs) == 1
        meta = read_epub_metadata(outputs[0])
        assert meta.title == "Il Nome della Rosa"

    def test_interactive_url_lookup_and_accept(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """Interactive match: URL lookup then accept writes updated EPUB."""
        output_dir = tmp_path / "output"

        search_candidate = _make_candidate("Weak Match", "Nobody", 0.3)
        url_candidate = _make_candidate(
            "The Templar Legacy", "Steve Berry", 1.0, isbn="9780345504500"
        )

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [search_candidate]
            mock_provider.lookup_by_url.return_value = url_candidate
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(sample_epub), "-o", str(output_dir)],
                input="u\nhttps://openlibrary.org/works/OL123W\na\n",
            )

        assert result.exit_code == 0
        outputs = list(output_dir.glob("*.epub"))
        assert len(outputs) == 1
        meta = read_epub_metadata(outputs[0])
        assert meta.title == "The Templar Legacy"


    def test_match_author_dash_title_epub(self, tmp_path: Path) -> None:
        """Match command parses 'Author - Title' format and finds candidates."""
        book = epub.EpubBook()
        book.set_identifier("author-dash-title-test")
        book.set_title("Steve Berry - The Templar Legacy")
        book.set_language("en")
        book.add_author("Unknown")

        chapter = epub.EpubHtml(title="Ch1", file_name="ch01.xhtml", lang="en")
        chapter.content = b"<html><body><p>Content.</p></body></html>"
        book.add_item(chapter)
        book.toc = [epub.Link("ch01.xhtml", "Ch1", "ch01")]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", chapter]

        epub_path = tmp_path / "author_dash_title.epub"
        epub.write_epub(str(epub_path), book)

        output_dir = tmp_path / "output"
        candidate = _make_candidate("The Templar Legacy", "Steve Berry", 0.95)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(epub_path), "-q", "-o", str(output_dir)],
            )

        assert result.exit_code == 0
        assert "1 matched" in result.output

        # Verify provider was called with clean title and detected author
        call_args = mock_provider.search_by_title_author.call_args
        assert call_args[0][0] == "The Templar Legacy"
        assert call_args[0][1] == "Steve Berry"

    def test_match_epub_with_subtitle(self, tmp_path: Path) -> None:
        """Match finds candidates for EPUB with subtitle in title via retry."""
        from typing import Any

        from bookery.metadata.openlibrary import OpenLibraryProvider
        from tests.fixtures.openlibrary_responses import (
            SEARCH_RESPONSE,
            SEARCH_RESPONSE_EMPTY,
        )

        book = epub.EpubBook()
        book.set_identifier("subtitle-test")
        book.set_title("The King's Deception: A Novel")
        book.set_language("en")
        book.add_author("Steve Berry")

        chapter = epub.EpubHtml(title="Ch1", file_name="ch01.xhtml", lang="en")
        chapter.content = b"<html><body><p>Content.</p></body></html>"
        book.add_item(chapter)
        book.toc = [epub.Link("ch01.xhtml", "Ch1", "ch01")]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", chapter]

        epub_path = tmp_path / "subtitle_title.epub"
        epub.write_epub(str(epub_path), book)

        output_dir = tmp_path / "output"

        # Use a real provider with a fake HTTP client that returns empty
        # for subtitle search and results for stripped title
        def fake_get(url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
            if "/search.json" in url and params:
                if ":" in params.get("title", ""):
                    return SEARCH_RESPONSE_EMPTY
                return SEARCH_RESPONSE
            return {}

        fake_client = MagicMock()
        fake_client.get.side_effect = fake_get
        real_provider = OpenLibraryProvider(http_client=fake_client)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_fn.return_value = real_provider

            runner = CliRunner()
            # Low threshold since fixture data titles won't exactly match
            result = runner.invoke(
                cli,
                ["match", str(epub_path), "-q", "-t", "0.1", "-o", str(output_dir)],
            )

        assert result.exit_code == 0
        assert "1 matched" in result.output

    def test_match_unknown_author_epub(self, tmp_path: Path) -> None:
        """Match command finds candidates for EPUB with 'Unknown' author."""
        book = epub.EpubBook()
        book.set_identifier("unknown-author-test")
        book.set_title("The King's Deception")
        book.set_language("en")
        book.add_author("Unknown")

        chapter = epub.EpubHtml(title="Ch1", file_name="ch01.xhtml", lang="en")
        chapter.content = b"<html><body><p>Content.</p></body></html>"
        book.add_item(chapter)
        book.toc = [epub.Link("ch01.xhtml", "Ch1", "ch01")]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", chapter]

        epub_path = tmp_path / "unknown_author.epub"
        epub.write_epub(str(epub_path), book)

        output_dir = tmp_path / "output"
        candidate = _make_candidate("The King's Deception", "Steve Berry", 0.95)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(epub_path), "-q", "-o", str(output_dir)],
            )

        assert result.exit_code == 0
        assert "1 matched" in result.output

        # Verify provider was NOT called with "Unknown" as author
        call_args = mock_provider.search_by_title_author.call_args
        author_arg = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("author")
        assert author_arg is None

    def test_match_hyphenated_isbn_epub(self, tmp_path: Path) -> None:
        """Match command resolves an EPUB with a hyphenated ISBN."""
        book = epub.EpubBook()
        book.set_identifier("isbn:978-0-345-52971-8")
        book.set_title("The King's Deception")
        book.set_language("en")
        book.add_author("Steve Berry")
        book.add_metadata("DC", "identifier", "978-0-345-52971-8")

        chapter = epub.EpubHtml(title="Ch1", file_name="ch01.xhtml", lang="en")
        chapter.content = b"<html><body><p>Content.</p></body></html>"
        book.add_item(chapter)
        book.toc = [epub.Link("ch01.xhtml", "Ch1", "ch01")]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", chapter]

        epub_path = tmp_path / "hyphenated_isbn.epub"
        epub.write_epub(str(epub_path), book)

        output_dir = tmp_path / "output"
        candidate = _make_candidate("The King's Deception", "Steve Berry", 1.0)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(epub_path), "-q", "-o", str(output_dir)],
            )

        assert result.exit_code == 0
        assert "1 matched" in result.output


class TestBatchModeEndToEnd:
    """End-to-end tests for batch mode features."""

    def test_resume_skips_already_output(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """Resume mode skips files that already exist in output directory."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / sample_epub.name).write_text("already done")

        candidate = _make_candidate("Match", "Author", 0.95)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "match", str(sample_epub), "-q",
                    "--resume", "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0
        assert "already processed" in result.output.lower()

    def test_no_resume_reprocesses(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """--no-resume processes files even if output already exists."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / sample_epub.name).write_text("stale copy")

        candidate = _make_candidate("Reprocessed", "Author", 0.95)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "match", str(sample_epub), "-q",
                    "--no-resume", "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0
        assert "1 matched" in result.output
        # The original "stale copy" still exists, plus a new collision-suffixed file
        epubs = list(output_dir.glob("*.epub"))
        assert len(epubs) == 2
        # One should have the _1 collision suffix
        assert any("_1" in p.stem for p in epubs)

    def test_threshold_changes_quiet_behavior(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """Lower threshold accepts candidates that default would skip."""
        output_dir = tmp_path / "output"
        # Candidate at 0.65 — below default 0.8 threshold
        candidate = _make_candidate("Low Confidence Match", "Author", 0.65)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            # With default threshold (0.8), this would be skipped
            result_default = runner.invoke(
                cli,
                [
                    "match", str(sample_epub), "-q",
                    "-o", str(output_dir),
                ],
            )

        assert "skipped" in result_default.output

        output_dir2 = tmp_path / "output2"

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            # With threshold 0.5, this should be accepted
            result_low = runner.invoke(
                cli,
                [
                    "match", str(sample_epub), "-q",
                    "-t", "0.5", "-o", str(output_dir2),
                ],
            )

        assert "1 matched" in result_low.output

    def test_batch_accept_remaining(
        self, sample_epub: Path, minimal_epub: Path, tmp_path: Path
    ) -> None:
        """[A] accepts remaining files above threshold without prompting."""
        scan_dir = tmp_path / "books"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "book1.epub")
        shutil.copy(minimal_epub, scan_dir / "book2.epub")
        output_dir = tmp_path / "output"

        candidate = _make_candidate("Matched Title", "Author", 0.9)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            # User enters 'A' on first file, second should auto-accept
            result = runner.invoke(
                cli,
                ["match", str(scan_dir), "-o", str(output_dir)],
                input="A\n",
            )

        assert result.exit_code == 0
        assert "2 matched" in result.output

    def test_batch_skip_remaining(
        self, sample_epub: Path, minimal_epub: Path, tmp_path: Path
    ) -> None:
        """[S] skips all remaining files without prompting."""
        scan_dir = tmp_path / "books"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "book1.epub")
        shutil.copy(minimal_epub, scan_dir / "book2.epub")
        output_dir = tmp_path / "output"

        candidate = _make_candidate("Matched Title", "Author", 0.9)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_fn.return_value = mock_provider

            runner = CliRunner()
            # User enters 'S' on first file, both should be skipped
            result = runner.invoke(
                cli,
                ["match", str(scan_dir), "-o", str(output_dir)],
                input="S\n",
            )

        assert result.exit_code == 0
        assert "2 skipped" in result.output
        # No files should be written
        if output_dir.exists():
            assert len(list(output_dir.glob("*.epub"))) == 0

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

        # Verify output shows normalization info
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

# ABOUTME: End-to-end tests for the bookery convert CLI command.
# ABOUTME: Tests the full convert pipeline using CliRunner with mocked MOBI extraction.

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli
from bookery.formats.mobi import MobiExtractResult, MobiReadError


def _make_valid_epub(path: Path, title: str = "Test Book", author: str = "Author") -> None:
    """Create a minimal valid EPUB at the given path."""
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)
    chapter = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    chapter.content = b"<html><body><p>Content</p></body></html>"
    book.add_item(chapter)
    book.toc = [epub.Link("ch1.xhtml", "Ch1", "ch1")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)


def _mock_extract_to_epub(tmp_path: Path, epub_title: str = "Converted Book"):
    """Create a mock extract_mobi that returns a fresh EPUB result per call."""
    call_count = 0

    def side_effect(path):
        nonlocal call_count
        call_count += 1
        extract_dir = tmp_path / f"mobi_extract_{call_count}"
        extract_dir.mkdir(exist_ok=True)
        epub_file = extract_dir / "book.epub"
        _make_valid_epub(epub_file, title=epub_title)
        return MobiExtractResult(
            tempdir=extract_dir,
            format="epub",
            epub_path=epub_file,
        )

    return side_effect


class TestConvertCliSingleFile:
    """E2E tests for converting a single MOBI file."""

    def test_converts_single_file(self, tmp_path: Path) -> None:
        """Converts a single MOBI file and reports success."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = _mock_extract_to_epub(tmp_path)
            result = runner.invoke(cli, [
                "convert", str(mobi_file), "-o", str(output_dir),
            ])

        assert result.exit_code == 0, result.output
        assert "1 converted" in result.output
        assert (output_dir / "book.epub").exists()

    def test_no_mobi_files_message(self, tmp_path: Path) -> None:
        """Shows a message when no MOBI files are found."""
        not_mobi = tmp_path / "readme.txt"
        not_mobi.write_text("not a mobi")

        runner = CliRunner()
        result = runner.invoke(cli, ["convert", str(not_mobi)])

        assert result.exit_code == 0
        assert "No MOBI files found" in result.output


class TestConvertCliBatch:
    """E2E tests for converting a directory of MOBI files."""

    def test_converts_directory(self, tmp_path: Path) -> None:
        """Converts all MOBI files in a directory."""
        mobi_dir = tmp_path / "mobis"
        mobi_dir.mkdir()
        (mobi_dir / "book1.mobi").write_bytes(b"fake1")
        (mobi_dir / "book2.mobi").write_bytes(b"fake2")
        (mobi_dir / "readme.txt").write_text("ignore me")
        output_dir = tmp_path / "output"

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = _mock_extract_to_epub(tmp_path)
            result = runner.invoke(cli, [
                "convert", str(mobi_dir), "-o", str(output_dir),
            ])

        assert result.exit_code == 0, result.output
        assert "2 converted" in result.output


class TestConvertCliForce:
    """E2E tests for --force flag."""

    def test_force_overwrites_existing(self, tmp_path: Path) -> None:
        """--force overwrites existing output files."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        existing = output_dir / "book.epub"
        existing.write_bytes(b"old content")

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = _mock_extract_to_epub(tmp_path)
            result = runner.invoke(cli, [
                "convert", str(mobi_file), "-o", str(output_dir), "--force",
            ])

        assert result.exit_code == 0, result.output
        assert "1 converted" in result.output
        # File should be overwritten (different content)
        assert existing.read_bytes() != b"old content"


class TestConvertCliSkip:
    """E2E tests for skip counting when output already exists."""

    def test_skip_without_force_reports_skipped(self, tmp_path: Path) -> None:
        """Running convert twice without --force reports '1 skipped', not '1 converted'."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        runner = CliRunner()
        # First run: actually converts
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = _mock_extract_to_epub(tmp_path)
            first = runner.invoke(cli, [
                "convert", str(mobi_file), "-o", str(output_dir),
            ])
        assert first.exit_code == 0, first.output
        assert "1 converted" in first.output

        # Second run: should skip (output already exists, no --force)
        second = runner.invoke(cli, [
            "convert", str(mobi_file), "-o", str(output_dir),
        ])
        assert second.exit_code == 0, second.output
        assert "1 skipped" in second.output
        assert "converted" not in second.output


class TestConvertCliErrors:
    """E2E tests for error handling."""

    def test_error_output_for_corrupt_file(self, tmp_path: Path) -> None:
        """Shows error for corrupt/DRM MOBI files."""
        mobi_file = tmp_path / "drm.mobi"
        mobi_file.write_bytes(b"drm content")
        output_dir = tmp_path / "output"

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = MobiReadError("DRM protected")
            result = runner.invoke(cli, [
                "convert", str(mobi_file), "-o", str(output_dir),
            ])

        assert result.exit_code == 0
        assert "1 error" in result.output

    def test_summary_counts(self, tmp_path: Path) -> None:
        """Summary shows correct counts for mixed results."""
        mobi_dir = tmp_path / "mobis"
        mobi_dir.mkdir()
        (mobi_dir / "good.mobi").write_bytes(b"good")
        (mobi_dir / "bad.mobi").write_bytes(b"bad")
        output_dir = tmp_path / "output"

        call_count = 0

        def mixed_extract(path):
            nonlocal call_count
            call_count += 1
            if "bad" in path.name:
                raise MobiReadError("corrupt file")
            return _mock_extract_to_epub(tmp_path)(path)

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = mixed_extract
            result = runner.invoke(cli, [
                "convert", str(mobi_dir), "-o", str(output_dir),
            ])

        assert result.exit_code == 0, result.output
        assert "1 converted" in result.output
        assert "1 error" in result.output


def _mock_extract_to_html_with_opf(tmp_path: Path):
    """Create a mock extract_mobi that returns HTML with OPF metadata and images."""
    call_count = 0

    def side_effect(path):
        nonlocal call_count
        call_count += 1
        extract_dir = tmp_path / f"mobi_extract_{call_count}"
        mobi7_dir = extract_dir / "mobi7"
        mobi7_dir.mkdir(parents=True)

        html_file = mobi7_dir / "book.html"
        html_file.write_text(
            '<html><body><img src="Images/cover.jpg"/><p>Content</p></body></html>'
        )

        opf_file = mobi7_dir / "content.opf"
        opf_file.write_text("""\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>The Martian</dc:title>
    <dc:creator>Andy Weir</dc:creator>
    <dc:language>en</dc:language>
    <dc:publisher>Crown Publishing</dc:publisher>
  </metadata>
</package>
""")

        images_dir = mobi7_dir / "Images"
        images_dir.mkdir()
        (images_dir / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0fake-jpg")

        return MobiExtractResult(
            tempdir=extract_dir,
            format="html",
            html_path=html_file,
            opf_path=opf_file,
            images_dir=images_dir,
        )

    return side_effect


class TestConvertCliMobi7Metadata:
    """E2E tests for MOBI7 conversion preserving OPF metadata and images."""

    def test_mobi7_preserves_metadata(self, tmp_path: Path) -> None:
        """MOBI7 conversion embeds OPF metadata in the output EPUB."""
        from bookery.formats.epub import read_epub_metadata

        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = _mock_extract_to_html_with_opf(tmp_path)
            result = runner.invoke(cli, [
                "convert", str(mobi_file), "-o", str(output_dir),
            ])

        assert result.exit_code == 0, result.output
        assert "1 converted" in result.output

        epub_path = output_dir / "book.epub"
        assert epub_path.exists()

        metadata = read_epub_metadata(epub_path)
        assert metadata.title == "The Martian"
        assert "Andy Weir" in metadata.authors

    def test_mobi7_includes_images(self, tmp_path: Path) -> None:
        """MOBI7 conversion includes images in the output EPUB."""
        import ebooklib

        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = _mock_extract_to_html_with_opf(tmp_path)
            result = runner.invoke(cli, [
                "convert", str(mobi_file), "-o", str(output_dir),
            ])

        assert result.exit_code == 0, result.output

        epub_path = output_dir / "book.epub"
        book = epub.read_epub(str(epub_path), options={"ignore_ncx": True})
        cover_items = [
            item for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_COVER
        ]
        assert len(cover_items) == 1
        assert cover_items[0].get_name() == "Images/cover.jpg"


def _mock_extract_to_html_with_ncx(tmp_path: Path):
    """Create a mock extract_mobi that returns HTML with NCX TOC."""
    call_count = 0

    def side_effect(path):
        nonlocal call_count
        call_count += 1
        extract_dir = tmp_path / f"mobi_extract_ncx_{call_count}"
        mobi7_dir = extract_dir / "mobi7"
        mobi7_dir.mkdir(parents=True)

        html_file = mobi7_dir / "book.html"
        html_file.write_text(
            '<html><body>'
            '<p>Book preamble</p>'
            '<a id="filepos000100"></a><h1>Chapter 1</h1>'
            '<p>First chapter content.</p>'
            '<a id="filepos000500"></a><h1>Chapter 2</h1>'
            '<p>Second chapter content.</p>'
            '<a id="filepos001000"></a><h1>Chapter 3</h1>'
            '<p>Third chapter content.</p>'
            '</body></html>'
        )

        ncx_file = mobi7_dir / "toc.ncx"
        ncx_file.write_text("""\
<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="np1" playOrder="1">
      <navLabel><text>Chapter 1</text></navLabel>
      <content src="book.html#filepos000100"/>
    </navPoint>
    <navPoint id="np2" playOrder="2">
      <navLabel><text>Chapter 2</text></navLabel>
      <content src="book.html#filepos000500"/>
    </navPoint>
    <navPoint id="np3" playOrder="3">
      <navLabel><text>Chapter 3</text></navLabel>
      <content src="book.html#filepos001000"/>
    </navPoint>
  </navMap>
</ncx>
""")

        opf_file = mobi7_dir / "content.opf"
        opf_file.write_text("""\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>The Martian</dc:title>
    <dc:creator>Andy Weir</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
</package>
""")

        return MobiExtractResult(
            tempdir=extract_dir,
            format="html",
            html_path=html_file,
            opf_path=opf_file,
            ncx_path=ncx_file,
        )

    return side_effect


class TestConvertCliNcxChapters:
    """E2E tests for MOBI7 conversion with NCX chapter splitting."""

    def test_ncx_produces_multi_chapter_epub(self, tmp_path: Path) -> None:
        """CLI convert with NCX produces EPUB with multiple TOC entries."""
        import ebooklib

        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = _mock_extract_to_html_with_ncx(tmp_path)
            result = runner.invoke(cli, [
                "convert", str(mobi_file), "-o", str(output_dir),
            ])

        assert result.exit_code == 0, result.output
        assert "1 converted" in result.output

        epub_path = output_dir / "book.epub"
        assert epub_path.exists()

        book = epub.read_epub(str(epub_path), options={"ignore_ncx": True})
        assert len(book.toc) == 3

        # Verify all chapter content is present
        doc_items = [
            item for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_DOCUMENT
        ]
        all_content = b"".join(
            item.get_content() for item in doc_items
        )
        assert b"First chapter content" in all_content
        assert b"Second chapter content" in all_content
        assert b"Third chapter content" in all_content

    def test_ncx_preserves_metadata(self, tmp_path: Path) -> None:
        """NCX-split EPUB still preserves OPF metadata."""
        from bookery.formats.epub import read_epub_metadata

        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = _mock_extract_to_html_with_ncx(tmp_path)
            result = runner.invoke(cli, [
                "convert", str(mobi_file), "-o", str(output_dir),
            ])

        assert result.exit_code == 0, result.output

        metadata = read_epub_metadata(output_dir / "book.epub")
        assert metadata.title == "The Martian"
        assert "Andy Weir" in metadata.authors


class TestConvertCliMatch:
    """E2E tests for --match flag integration."""

    def test_match_flag_chains_into_match_pipeline(self, tmp_path: Path) -> None:
        """--match flag triggers match pipeline after conversion."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        runner = CliRunner()
        with (
            patch("bookery.core.converter.extract_mobi") as mock_extract,
            patch("bookery.cli.commands.convert_cmd._create_provider") as mock_provider_fn,
            patch("bookery.cli.commands.convert_cmd.match_one") as mock_match,
        ):
            mock_extract.side_effect = _mock_extract_to_epub(tmp_path)
            mock_provider = MagicMock()
            mock_provider_fn.return_value = mock_provider
            mock_match.return_value = MagicMock(
                status="matched", output_path=tmp_path / "out.epub",
            )
            result = runner.invoke(cli, [
                "convert", str(mobi_file), "-o", str(output_dir), "--match", "-q",
            ])

        assert result.exit_code == 0, result.output
        mock_match.assert_called_once()

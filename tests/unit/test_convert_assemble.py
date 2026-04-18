# ABOUTME: Unit tests for convert.assemble — EPUB produced from MagazineDoc via ebooklib.

import zipfile
from pathlib import Path

import pytest
from ebooklib import ITEM_DOCUMENT, epub

from bookery.convert.assemble import assemble
from bookery.convert.types import Article, MagazineDoc


@pytest.fixture
def sample_doc() -> MagazineDoc:
    return MagazineDoc(
        publication="The New Yorker",
        issue="April 13, 2026",
        articles=[
            Article(
                title="Piece One",
                section="FICTION",
                byline="BY JANE DOE",
                dek="A short teaser.",
                body="First paragraph of piece one.\n\nSecond paragraph of piece one.",
            ),
            Article(
                title="Piece Two",
                body="Only paragraph of piece two.",
            ),
        ],
    )


def test_assemble_writes_valid_epub(tmp_path: Path, sample_doc: MagazineDoc) -> None:
    path = assemble(sample_doc, tmp_path, stem="book")
    assert path.exists()
    assert path.suffix == ".epub"

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert any("kobo.css" in n for n in names)


def test_assemble_has_chapter_files(tmp_path: Path, sample_doc: MagazineDoc) -> None:
    path = assemble(sample_doc, tmp_path, stem="book")
    book = epub.read_epub(str(path))
    docs = [item for item in book.get_items() if item.get_type() == ITEM_DOCUMENT]
    # Two articles + nav
    assert len(docs) >= 3


def test_assemble_renders_metadata_headers(
    tmp_path: Path, sample_doc: MagazineDoc
) -> None:
    path = assemble(sample_doc, tmp_path, stem="book")
    book = epub.read_epub(str(path))
    chapter_items = [
        item for item in book.get_items()
        if item.get_type() == ITEM_DOCUMENT and "chap_001" in item.file_name
    ]
    assert chapter_items
    content = chapter_items[0].content.decode("utf-8")
    assert "<h1>Piece One</h1>" in content
    assert '<p class="section">FICTION</p>' in content
    assert '<p class="byline">BY JANE DOE</p>' in content
    assert '<p class="dek">A short teaser.</p>' in content
    assert "<p>First paragraph of piece one.</p>" in content
    assert "<p>Second paragraph of piece one.</p>" in content


def test_assemble_title_from_publication_and_issue(
    tmp_path: Path, sample_doc: MagazineDoc
) -> None:
    path = assemble(sample_doc, tmp_path, stem="raw_stem")
    book = epub.read_epub(str(path))
    assert (
        book.get_metadata("DC", "title")[0][0]
        == "The New Yorker - April 13, 2026"
    )


def test_assemble_title_falls_back_to_hint() -> None:
    doc = MagazineDoc(articles=[Article(title="Only", body="Body.")])
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        path = assemble(
            doc, Path(td), stem="raw_stem", title_hint="My Book"
        )
        book = epub.read_epub(str(path))
        assert book.get_metadata("DC", "title")[0][0] == "My Book"


def test_assemble_title_humanizes_stem_when_no_hint(tmp_path: Path) -> None:
    doc = MagazineDoc(articles=[Article(title="Only", body="Body.")])
    path = assemble(doc, tmp_path, stem="The_New_Yorker-2026-04-13")
    book = epub.read_epub(str(path))
    assert (
        book.get_metadata("DC", "title")[0][0] == "The New Yorker 2026 04 13"
    )


def test_assemble_empty_doc(tmp_path: Path) -> None:
    doc = MagazineDoc(articles=[])
    path = assemble(doc, tmp_path, stem="empty")
    assert path.exists()


def test_assemble_body_paragraph_splitting(tmp_path: Path) -> None:
    doc = MagazineDoc(
        articles=[
            Article(title="T", body="p1\n\np2\n\n\n\np3"),
        ]
    )
    path = assemble(doc, tmp_path, stem="book")
    book = epub.read_epub(str(path))
    chapter_items = [
        item for item in book.get_items()
        if item.get_type() == ITEM_DOCUMENT and "chap_001" in item.file_name
    ]
    content = chapter_items[0].content.decode("utf-8")
    assert content.count("<p>") == 3

# ABOUTME: Unit tests for convert.assemble — EPUB produced from ClassifiedDoc via ebooklib.

import zipfile
from pathlib import Path

import pytest
from ebooklib import ITEM_DOCUMENT, epub

from bookery.convert.assemble import assemble
from bookery.convert.types import ClassifiedBlock, ClassifiedChapter, ClassifiedDoc


@pytest.fixture
def sample_doc() -> ClassifiedDoc:
    return ClassifiedDoc(
        chapters=(
            ClassifiedChapter(
                title="Chapter One",
                blocks=(
                    ClassifiedBlock(text="Opening Line", kind="h1"),
                    ClassifiedBlock(text="Body paragraph one.", kind="p"),
                    ClassifiedBlock(text="Body paragraph two.", kind="p"),
                    ClassifiedBlock(text="A quoted passage.", kind="blockquote"),
                    ClassifiedBlock(text="First item", kind="li"),
                    ClassifiedBlock(text="Second item", kind="li"),
                    ClassifiedBlock(text="Back to prose.", kind="p"),
                ),
            ),
            ClassifiedChapter(
                title="Chapter Two",
                blocks=(
                    ClassifiedBlock(text="More prose here.", kind="p"),
                ),
            ),
        )
    )


def test_assemble_writes_valid_epub(tmp_path: Path, sample_doc: ClassifiedDoc) -> None:
    path = assemble(sample_doc, tmp_path, stem="book")
    assert path.exists()
    assert path.suffix == ".epub"

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert any("kobo.css" in n for n in names)


def test_assemble_has_chapter_files(tmp_path: Path, sample_doc: ClassifiedDoc) -> None:
    path = assemble(sample_doc, tmp_path, stem="book")
    book = epub.read_epub(str(path))
    docs = [item for item in book.get_items() if item.get_type() == ITEM_DOCUMENT]
    # Two chapters + nav
    assert len(docs) >= 3


def test_assemble_list_blocks_wrap_in_ul(tmp_path: Path, sample_doc: ClassifiedDoc) -> None:
    path = assemble(sample_doc, tmp_path, stem="book")
    book = epub.read_epub(str(path))
    chapter_items = [
        item for item in book.get_items()
        if item.get_type() == ITEM_DOCUMENT and "chap_001" in item.file_name
    ]
    assert chapter_items
    content = chapter_items[0].content.decode("utf-8")
    assert "<ul>" in content
    assert "</ul>" in content
    assert content.index("<ul>") < content.index("<li>First item</li>")


def test_assemble_title_from_hint(tmp_path: Path, sample_doc: ClassifiedDoc) -> None:
    path = assemble(
        sample_doc, tmp_path, stem="raw_stem", title_hint="The New Yorker - April 13 2026"
    )
    book = epub.read_epub(str(path))
    assert book.get_metadata("DC", "title")[0][0] == "The New Yorker - April 13 2026"


def test_assemble_title_from_humanized_stem(
    tmp_path: Path, sample_doc: ClassifiedDoc
) -> None:
    path = assemble(sample_doc, tmp_path, stem="The_New_Yorker-2026-04-13")
    book = epub.read_epub(str(path))
    assert (
        book.get_metadata("DC", "title")[0][0] == "The New Yorker 2026 04 13"
    )


def test_assemble_title_falls_back_to_h1_when_stem_already_plain(
    tmp_path: Path, sample_doc: ClassifiedDoc
) -> None:
    # stem with no separators — humanizer leaves it unchanged, so we fall back to h1.
    path = assemble(sample_doc, tmp_path, stem="book")
    book = epub.read_epub(str(path))
    assert book.get_metadata("DC", "title")[0][0] == "Opening Line"


def test_assemble_empty_doc(tmp_path: Path) -> None:
    doc = ClassifiedDoc(chapters=())
    path = assemble(doc, tmp_path, stem="empty")
    assert path.exists()

# ABOUTME: Unit tests for convert.types extraction dataclasses and pydantic models.

import dataclasses

import pytest
from pydantic import ValidationError

from bookery.convert.types import (
    Article,
    MagazineDoc,
    OutlineEntry,
    RawBlock,
    RawDoc,
    RawPage,
)

DATACLASS_TYPES = [
    RawBlock,
    RawPage,
    OutlineEntry,
    RawDoc,
]


@pytest.mark.parametrize("cls", DATACLASS_TYPES)
def test_all_frozen_with_slots(cls: type) -> None:
    assert dataclasses.is_dataclass(cls)
    assert hasattr(cls, "__slots__")
    params = cls.__dataclass_params__  # type: ignore[attr-defined]
    assert params.frozen is True


def test_raw_block_immutable() -> None:
    block = RawBlock(text="hi", page=1, bbox=(0, 0, 10, 10), font_size=12.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        block.text = "nope"  # type: ignore[misc]


def test_article_requires_title_and_body() -> None:
    art = Article(title="Hello", body="Para one.\n\nPara two.")
    assert art.title == "Hello"
    assert art.body.startswith("Para one.")
    assert art.section is None
    assert art.byline is None
    assert art.dek is None


def test_article_accepts_optional_fields() -> None:
    art = Article(
        title="Hello",
        section="FICTION",
        byline="BY JANE DOE",
        dek="A short teaser",
        body="Paragraph.",
    )
    assert art.section == "FICTION"
    assert art.byline == "BY JANE DOE"
    assert art.dek == "A short teaser"


def test_article_missing_required_raises() -> None:
    with pytest.raises(ValidationError):
        Article(title="x")  # type: ignore[call-arg]


def test_magazine_doc_defaults() -> None:
    doc = MagazineDoc(articles=[Article(title="Ch 1", body="Body.")])
    assert doc.publication is None
    assert doc.issue is None
    assert len(doc.articles) == 1


def test_magazine_doc_roundtrip_json() -> None:
    payload = {
        "publication": "The New Yorker",
        "issue": "April 13, 2026",
        "articles": [
            {"title": "A", "body": "a body"},
            {"title": "B", "section": "BOOKS", "body": "b body"},
        ],
    }
    doc = MagazineDoc.model_validate(payload)
    assert doc.publication == "The New Yorker"
    assert doc.articles[1].section == "BOOKS"

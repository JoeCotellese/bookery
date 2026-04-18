# ABOUTME: Unit tests confirming convert.types dataclasses are frozen with slots.

import dataclasses

import pytest

from bookery.convert.types import (
    ChapterPlan,
    ChapterSpan,
    ClassifiedBlock,
    ClassifiedChapter,
    ClassifiedDoc,
    CleanBlock,
    CleanDoc,
    OutlineEntry,
    RawBlock,
    RawDoc,
    RawPage,
)

ALL_TYPES = [
    RawBlock,
    RawPage,
    OutlineEntry,
    RawDoc,
    CleanBlock,
    CleanDoc,
    ChapterSpan,
    ChapterPlan,
    ClassifiedBlock,
    ClassifiedChapter,
    ClassifiedDoc,
]


@pytest.mark.parametrize("cls", ALL_TYPES)
def test_all_frozen_with_slots(cls: type) -> None:
    assert dataclasses.is_dataclass(cls)
    # Slots dataclasses have __slots__ defined.
    assert hasattr(cls, "__slots__")
    params = cls.__dataclass_params__  # type: ignore[attr-defined]
    assert params.frozen is True


def test_raw_block_immutable() -> None:
    block = RawBlock(text="hi", page=1, bbox=(0, 0, 10, 10), font_size=12.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        block.text = "nope"  # type: ignore[misc]


def test_classified_doc_default_warnings() -> None:
    doc = ClassifiedDoc(chapters=())
    assert doc.warnings == ()

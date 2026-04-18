# ABOUTME: Unit tests for convert.chapters — outline-first, heuristic fallback.

from bookery.convert.chapters import plan_chapters
from bookery.convert.types import CleanBlock, CleanDoc, OutlineEntry


def _doc(blocks: list[tuple[str, int, float]], outline: tuple[OutlineEntry, ...] = ()) -> CleanDoc:
    return CleanDoc(
        blocks=tuple(CleanBlock(text=t, page=p, font_size=s) for t, p, s in blocks),
        outline=outline,
    )


def test_outline_preferred_when_available() -> None:
    doc = _doc(
        blocks=[
            ("Intro body.", 1, 11.0),
            ("Chapter One", 2, 16.0),
            ("Body paragraph.", 2, 11.0),
            ("Chapter Two", 5, 16.0),
            ("More body.", 5, 11.0),
        ],
        outline=(
            OutlineEntry(title="Chapter One", page=2, level=1),
            OutlineEntry(title="Chapter Two", page=5, level=1),
        ),
    )
    plan = plan_chapters(doc)
    assert plan.source == "outline"
    titles = [s.title for s in plan.spans]
    assert titles == ["Chapter One", "Chapter Two"]
    assert plan.spans[0].start == 1
    assert plan.spans[0].end == 3
    assert plan.spans[1].start == 3
    assert plan.spans[1].end == 5


def test_heuristic_fallback_without_outline() -> None:
    doc = _doc(
        blocks=[
            ("Chapter 1", 1, 18.0),
            ("Body of chapter 1 first paragraph.", 1, 11.0),
            ("Body of chapter 1 second paragraph.", 2, 11.0),
            ("Body of chapter 1 third paragraph.", 2, 11.0),
            ("Chapter 2", 3, 18.0),
            ("Body of chapter 2 first paragraph.", 3, 11.0),
            ("Body of chapter 2 second paragraph.", 4, 11.0),
            ("Body of chapter 2 third paragraph.", 4, 11.0),
        ],
    )
    plan = plan_chapters(doc)
    assert plan.source == "heuristic"
    titles = [s.title for s in plan.spans]
    assert titles == ["Chapter 1", "Chapter 2"]


def test_heuristic_only_content_when_no_headings_detected() -> None:
    doc = _doc(
        blocks=[
            ("Just body text.", 1, 11.0),
            ("More body text.", 1, 11.0),
            ("Still more body.", 2, 11.0),
        ],
    )
    plan = plan_chapters(doc)
    assert plan.source == "heuristic"
    assert len(plan.spans) == 1
    assert plan.spans[0].title == "Content"
    assert plan.spans[0].start == 0
    assert plan.spans[0].end == 3


def test_empty_doc_empty_plan() -> None:
    doc = _doc(blocks=[], outline=())
    plan = plan_chapters(doc)
    assert plan.spans == ()
    assert plan.source == "heuristic"


def test_heuristic_front_matter_prepended() -> None:
    doc = _doc(
        blocks=[
            ("Title page content.", 1, 11.0),
            ("Copyright stuff.", 1, 11.0),
            ("Dedication line.", 2, 11.0),
            ("Chapter 1", 3, 18.0),
            ("Body one.", 3, 11.0),
            ("Body two.", 4, 11.0),
            ("Body three.", 4, 11.0),
        ],
    )
    plan = plan_chapters(doc)
    titles = [s.title for s in plan.spans]
    assert titles == ["Front Matter", "Chapter 1"]

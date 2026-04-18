# ABOUTME: Chapter planning — outline-preferred; font-size heuristic fallback.
# ABOUTME: Produces ChapterPlan of (title, start, end) block index spans over a CleanDoc.

from statistics import median

from bookery.convert.types import ChapterPlan, ChapterSpan, CleanDoc

HEURISTIC_FONT_MULTIPLE = 1.25
MIN_CHAPTER_BLOCKS = 3


def _from_outline(doc: CleanDoc) -> ChapterPlan | None:
    if not doc.outline:
        return None
    top_level = min(e.level for e in doc.outline)
    entries = [e for e in doc.outline if e.level == top_level]
    if not entries:
        return None
    # Stable sort by page so out-of-order outlines still map correctly.
    entries = sorted(entries, key=lambda e: e.page)

    starts: list[tuple[str, int]] = []
    for entry in entries:
        idx = _first_block_on_or_after(doc, entry.page)
        if idx is None:
            continue
        if starts and starts[-1][1] == idx:
            continue
        starts.append((entry.title, idx))
    if not starts:
        return None

    spans: list[ChapterSpan] = []
    for i, (title, start) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(doc.blocks)
        spans.append(ChapterSpan(title=title, start=start, end=end))
    return ChapterPlan(spans=tuple(spans), source="outline")


def _first_block_on_or_after(doc: CleanDoc, page: int) -> int | None:
    for idx, block in enumerate(doc.blocks):
        if block.page >= page:
            return idx
    return None


def _heuristic(doc: CleanDoc) -> ChapterPlan:
    if not doc.blocks:
        return ChapterPlan(spans=(), source="heuristic")
    sizes = [b.font_size for b in doc.blocks]
    baseline = median(sizes)
    threshold = baseline * HEURISTIC_FONT_MULTIPLE

    starts: list[tuple[str, int]] = []
    for idx, block in enumerate(doc.blocks):
        if block.font_size >= threshold and len(block.text) <= 120:
            if starts and idx - starts[-1][1] < MIN_CHAPTER_BLOCKS:
                continue
            starts.append((block.text.strip(), idx))

    if not starts:
        return ChapterPlan(
            spans=(ChapterSpan(title="Content", start=0, end=len(doc.blocks)),),
            source="heuristic",
        )

    # Prepend a "Front matter" chapter if the first detected heading isn't at index 0.
    if starts[0][1] > 0:
        starts.insert(0, ("Front Matter", 0))

    spans: list[ChapterSpan] = []
    for i, (title, start) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(doc.blocks)
        spans.append(ChapterSpan(title=title, start=start, end=end))
    return ChapterPlan(spans=tuple(spans), source="heuristic")


def plan_chapters(doc: CleanDoc) -> ChapterPlan:
    """Return a ChapterPlan using outline when available, falling back to font heuristics."""
    outline_plan = _from_outline(doc)
    if outline_plan is not None and outline_plan.spans:
        return outline_plan
    return _heuristic(doc)

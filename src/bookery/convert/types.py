# ABOUTME: Frozen dataclass hierarchy for PDF conversion stages.
# ABOUTME: RawDoc -> CleanDoc -> ClassifiedDoc; immutable snapshots between pipeline stages.

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RawBlock:
    text: str
    page: int
    # Bounding box in PDF coordinate space: (x0, top, x1, bottom)
    bbox: tuple[float, float, float, float]
    # Median font size across the block's characters
    font_size: float


@dataclass(frozen=True, slots=True)
class RawPage:
    number: int
    width: float
    height: float
    blocks: tuple[RawBlock, ...]


@dataclass(frozen=True, slots=True)
class OutlineEntry:
    title: str
    # 1-indexed page number this entry points at
    page: int
    level: int


@dataclass(frozen=True, slots=True)
class RawDoc:
    pages: tuple[RawPage, ...]
    outline: tuple[OutlineEntry, ...]


@dataclass(frozen=True, slots=True)
class CleanBlock:
    text: str
    page: int
    font_size: float


@dataclass(frozen=True, slots=True)
class CleanDoc:
    blocks: tuple[CleanBlock, ...]
    outline: tuple[OutlineEntry, ...]


@dataclass(frozen=True, slots=True)
class ChapterSpan:
    title: str
    # Inclusive start, exclusive end, indexing into CleanDoc.blocks
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ChapterPlan:
    spans: tuple[ChapterSpan, ...]
    # "outline" when derived from PDF outline, "heuristic" when inferred from font sizes
    source: str


@dataclass(frozen=True, slots=True)
class ClassifiedBlock:
    text: str
    # One of: h1, h2, h3, p, blockquote, li
    kind: str


@dataclass(frozen=True, slots=True)
class ClassifiedChapter:
    title: str
    blocks: tuple[ClassifiedBlock, ...]


@dataclass(frozen=True, slots=True)
class ClassifiedDoc:
    chapters: tuple[ClassifiedChapter, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

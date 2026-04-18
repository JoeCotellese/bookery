# ABOUTME: Types for PDF conversion — raw extraction dataclasses and semantic pydantic models.
# ABOUTME: RawDoc feeds the LLM; MagazineDoc is the validated semantic response used by assemble.

from dataclasses import dataclass

from pydantic import BaseModel


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


class Article(BaseModel):
    title: str
    section: str | None = None
    byline: str | None = None
    dek: str | None = None
    body: str


class MagazineDoc(BaseModel):
    publication: str | None = None
    issue: str | None = None
    articles: list[Article]

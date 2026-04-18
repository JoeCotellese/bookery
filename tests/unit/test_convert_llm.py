# ABOUTME: Unit tests for convert.llm — mocked openai client, cache hit/miss, retry, fallback.

import json
from pathlib import Path
from typing import Any

import pytest

from bookery.convert.cache import LLMCache
from bookery.convert.chapters import plan_chapters
from bookery.convert.llm import classify
from bookery.convert.types import ChapterPlan, ChapterSpan, CleanBlock, CleanDoc
from bookery.core.config import ConvertConfig


class FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = type("M", (), {"content": content})()


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def create(self, **_kwargs: Any) -> FakeResponse:
        self.calls += 1
        if not self.responses:
            raise RuntimeError("no more fake responses")
        return FakeResponse(self.responses.pop(0))


class FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self._completions = FakeCompletions(responses)
        self.chat = FakeChat(self._completions)


@pytest.fixture
def cache(tmp_path: Path) -> LLMCache:
    return LLMCache(tmp_path / "cache.db")


@pytest.fixture
def cfg() -> ConvertConfig:
    return ConvertConfig(llm_max_retries=3, prompt_version=1, llm_model="test-model")


def _doc_and_plan(texts: list[str]) -> tuple[CleanDoc, ChapterPlan]:
    doc = CleanDoc(
        blocks=tuple(CleanBlock(text=t, page=1, font_size=11.0) for t in texts),
        outline=(),
    )
    plan = ChapterPlan(
        spans=(ChapterSpan(title="Chapter One", start=0, end=len(texts)),),
        source="heuristic",
    )
    return doc, plan


def test_classify_happy_path(cache: LLMCache, cfg: ConvertConfig) -> None:
    doc, plan = _doc_and_plan(["Title heading", "A paragraph.", "Another paragraph."])
    response = json.dumps({"classifications": ["h1", "p", "p"]})
    fake = FakeClient([response])
    result = classify(doc, plan, cache, cfg, client_factory=lambda _c: fake)
    assert len(result.chapters) == 1
    kinds = [b.kind for b in result.chapters[0].blocks]
    assert kinds == ["h1", "p", "p"]


def test_cache_hit_skips_llm(cache: LLMCache, cfg: ConvertConfig) -> None:
    doc, plan = _doc_and_plan(["A.", "B."])
    response = json.dumps({"classifications": ["p", "p"]})
    fake1 = FakeClient([response])
    classify(doc, plan, cache, cfg, client_factory=lambda _c: fake1)
    assert fake1._completions.calls == 1

    fake2 = FakeClient([])
    result = classify(doc, plan, cache, cfg, client_factory=lambda _c: fake2)
    assert fake2._completions.calls == 0
    assert [b.kind for b in result.chapters[0].blocks] == ["p", "p"]


def test_malformed_json_retries_then_succeeds(
    cache: LLMCache, cfg: ConvertConfig
) -> None:
    doc, plan = _doc_and_plan(["X.", "Y."])
    good = json.dumps({"classifications": ["p", "p"]})
    fake = FakeClient(["not json at all", good])
    result = classify(doc, plan, cache, cfg, client_factory=lambda _c: fake)
    assert fake._completions.calls == 2
    assert [b.kind for b in result.chapters[0].blocks] == ["p", "p"]


def test_all_retries_fail_falls_back_to_heuristic(
    cache: LLMCache, cfg: ConvertConfig
) -> None:
    doc, plan = _doc_and_plan(["Big Heading", "body text here."])
    # Make the first block significantly larger → heuristic should emit h2 for it.
    doc = CleanDoc(
        blocks=(
            CleanBlock(text="Big Heading", page=1, font_size=18.0),
            CleanBlock(text="body text here.", page=1, font_size=11.0),
        ),
        outline=(),
    )
    fake = FakeClient(["bad", "still bad", "also bad"])
    result = classify(doc, plan, cache, cfg, client_factory=lambda _c: fake)
    kinds = [b.kind for b in result.chapters[0].blocks]
    assert kinds[0] == "h2"
    assert kinds[1] == "p"
    assert any("heuristic" in w for w in result.warnings)


def test_invalid_kind_coerced_to_p(cache: LLMCache, cfg: ConvertConfig) -> None:
    doc, plan = _doc_and_plan(["X."])
    response = json.dumps({"classifications": ["bogus"]})
    fake = FakeClient([response])
    result = classify(doc, plan, cache, cfg, client_factory=lambda _c: fake)
    assert result.chapters[0].blocks[0].kind == "p"


def test_empty_plan_returns_empty_doc(cache: LLMCache, cfg: ConvertConfig) -> None:
    empty = CleanDoc(blocks=(), outline=())
    empty_plan = plan_chapters(empty)
    result = classify(empty, empty_plan, cache, cfg, client_factory=lambda _c: FakeClient([]))
    assert result.chapters == ()

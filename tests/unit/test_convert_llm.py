# ABOUTME: Unit tests for convert.llm — mocked openai client, cache hit/miss, retry, bad-response.

from pathlib import Path
from typing import Any

import pytest

from bookery.convert.cache import LLMCache
from bookery.convert.errors import LLMBadResponse
from bookery.convert.llm import extract_semantic
from bookery.convert.types import Article, MagazineDoc, RawBlock, RawDoc, RawPage
from bookery.core.config import SemanticConfig


class FakeMessage:
    def __init__(self, parsed: MagazineDoc | None = None, content: str = "") -> None:
        self.content = content
        self.parsed = parsed


class FakeChoice:
    def __init__(
        self, message: FakeMessage, finish_reason: str = "stop"
    ) -> None:
        self.message = message
        self.finish_reason = finish_reason


class FakeResponse:
    def __init__(
        self, message: FakeMessage, finish_reason: str = "stop"
    ) -> None:
        self.choices = [FakeChoice(message, finish_reason)]


class FakeCompletions:
    def __init__(
        self,
        messages: list[FakeMessage],
        finish_reasons: list[str] | None = None,
    ) -> None:
        self.messages = list(messages)
        self.finish_reasons = list(finish_reasons) if finish_reasons else []
        self.calls = 0
        self.last_kwargs: dict[str, Any] | None = None

    def parse(self, **kwargs: Any) -> FakeResponse:
        self.calls += 1
        self.last_kwargs = kwargs
        if not self.messages:
            raise RuntimeError("no more fake responses")
        msg = self.messages.pop(0)
        finish = self.finish_reasons.pop(0) if self.finish_reasons else "stop"
        return FakeResponse(msg, finish_reason=finish)


class FakeBetaChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeBeta:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = FakeBetaChat(completions)


class FakeClient:
    def __init__(
        self,
        messages: list[FakeMessage],
        finish_reasons: list[str] | None = None,
    ) -> None:
        self._completions = FakeCompletions(messages, finish_reasons)
        self.beta = FakeBeta(self._completions)


@pytest.fixture
def cache(tmp_path: Path) -> LLMCache:
    return LLMCache(tmp_path / "cache.db")


@pytest.fixture
def cfg() -> SemanticConfig:
    return SemanticConfig(
        provider="lm-studio",
        model="test-model",
        base_url="http://localhost:1234/v1",
        llm_max_retries=2,
    )


def _raw_doc(texts: list[str]) -> RawDoc:
    blocks = tuple(
        RawBlock(text=t, page=1, bbox=(0, 0, 100, 20), font_size=11.0)
        for t in texts
    )
    page = RawPage(number=1, width=600, height=800, blocks=blocks)
    return RawDoc(pages=(page,), outline=())


def _doc() -> MagazineDoc:
    return MagazineDoc(
        publication="The New Yorker",
        issue="April 13, 2026",
        articles=[
            Article(title="Piece One", body="Paragraph one.\n\nParagraph two."),
            Article(title="Piece Two", section="BOOKS", body="Body here."),
        ],
    )


def test_extract_happy_path(cache: LLMCache, cfg: SemanticConfig) -> None:
    raw = _raw_doc(["Some title", "Some paragraph."])
    doc = _doc()
    fake = FakeClient([FakeMessage(parsed=doc)])
    result = extract_semantic(raw, cfg, cache, client_factory=lambda _c: fake)
    assert len(result.articles) == 2
    assert result.publication == "The New Yorker"
    assert fake._completions.calls == 1


def test_cache_hit_skips_llm(cache: LLMCache, cfg: SemanticConfig) -> None:
    raw = _raw_doc(["A", "B"])
    doc = _doc()
    fake1 = FakeClient([FakeMessage(parsed=doc)])
    extract_semantic(raw, cfg, cache, client_factory=lambda _c: fake1)
    assert fake1._completions.calls == 1

    fake2 = FakeClient([])
    result = extract_semantic(raw, cfg, cache, client_factory=lambda _c: fake2)
    assert fake2._completions.calls == 0
    assert len(result.articles) == 2


def test_empty_articles_retries_then_raises(
    cache: LLMCache, cfg: SemanticConfig
) -> None:
    raw = _raw_doc(["garbled"])
    empty = MagazineDoc(articles=[])
    fake = FakeClient([FakeMessage(parsed=empty), FakeMessage(parsed=empty)])
    with pytest.raises(LLMBadResponse):
        extract_semantic(raw, cfg, cache, client_factory=lambda _c: fake)
    assert fake._completions.calls == 2


def test_malformed_json_retries_then_succeeds(
    cache: LLMCache, cfg: SemanticConfig
) -> None:
    raw = _raw_doc(["x"])
    good = _doc()
    # First response: no parsed, invalid content → LLMBadResponse. Second: valid parsed.
    fake = FakeClient(
        [
            FakeMessage(parsed=None, content="not valid json"),
            FakeMessage(parsed=good),
        ]
    )
    result = extract_semantic(raw, cfg, cache, client_factory=lambda _c: fake)
    assert fake._completions.calls == 2
    assert len(result.articles) == 2


def test_empty_content_raises_after_retries(
    cache: LLMCache, cfg: SemanticConfig
) -> None:
    raw = _raw_doc(["x"])
    fake = FakeClient(
        [
            FakeMessage(parsed=None, content=""),
            FakeMessage(parsed=None, content=""),
        ]
    )
    with pytest.raises(LLMBadResponse):
        extract_semantic(raw, cfg, cache, client_factory=lambda _c: fake)


def test_truncated_response_raises(cache: LLMCache, cfg: SemanticConfig) -> None:
    """finish_reason=='length' means the model hit max_tokens mid-output."""
    raw = _raw_doc(["x"])
    doc = _doc()
    fake = FakeClient(
        [FakeMessage(parsed=doc), FakeMessage(parsed=doc)],
        finish_reasons=["length", "length"],
    )
    with pytest.raises(LLMBadResponse, match="truncated"):
        extract_semantic(raw, cfg, cache, client_factory=lambda _c: fake)


def test_truncated_error_mentions_max_tokens(
    cache: LLMCache, cfg: SemanticConfig
) -> None:
    raw = _raw_doc(["x"])
    doc = _doc()
    fake = FakeClient(
        [FakeMessage(parsed=doc)], finish_reasons=["length"]
    )
    cfg_once = SemanticConfig(
        provider="lm-studio",
        model="test-model",
        base_url="http://localhost:1234/v1",
        llm_max_retries=1,
    )
    with pytest.raises(LLMBadResponse) as exc_info:
        extract_semantic(raw, cfg_once, cache, client_factory=lambda _c: fake)
    assert "max_tokens" in str(exc_info.value)


def test_cache_key_varies_with_max_tokens(
    cache: LLMCache, cfg: SemanticConfig
) -> None:
    """Changing max_tokens must invalidate the cached response."""
    raw = _raw_doc(["x"])
    doc = _doc()

    # First call with max_tokens=0 (unset) → cache miss, populates.
    cfg_a = SemanticConfig(
        provider="lm-studio",
        model="test-model",
        base_url="http://localhost:1234/v1",
        llm_max_retries=2,
        max_tokens=0,
    )
    fake_a = FakeClient([FakeMessage(parsed=doc)])
    extract_semantic(raw, cfg_a, cache, client_factory=lambda _c: fake_a)
    assert fake_a._completions.calls == 1

    # Same config: cache hit.
    fake_a2 = FakeClient([])
    extract_semantic(raw, cfg_a, cache, client_factory=lambda _c: fake_a2)
    assert fake_a2._completions.calls == 0

    # Different max_tokens: cache miss, real call.
    cfg_b = SemanticConfig(
        provider="lm-studio",
        model="test-model",
        base_url="http://localhost:1234/v1",
        llm_max_retries=2,
        max_tokens=4096,
    )
    fake_b = FakeClient([FakeMessage(parsed=doc)])
    extract_semantic(raw, cfg_b, cache, client_factory=lambda _c: fake_b)
    assert fake_b._completions.calls == 1


def test_max_tokens_sent_to_client_when_set(
    cache: LLMCache, cfg: SemanticConfig
) -> None:
    raw = _raw_doc(["x"])
    doc = _doc()
    cfg_big = SemanticConfig(
        provider="lm-studio",
        model="test-model",
        base_url="http://localhost:1234/v1",
        llm_max_retries=2,
        max_tokens=262144,
    )
    fake = FakeClient([FakeMessage(parsed=doc)])
    extract_semantic(raw, cfg_big, cache, client_factory=lambda _c: fake)
    assert fake._completions.last_kwargs is not None
    assert fake._completions.last_kwargs.get("max_tokens") == 262144


def test_max_tokens_omitted_when_zero(
    cache: LLMCache, cfg: SemanticConfig
) -> None:
    raw = _raw_doc(["x"])
    doc = _doc()
    fake = FakeClient([FakeMessage(parsed=doc)])
    extract_semantic(raw, cfg, cache, client_factory=lambda _c: fake)
    assert fake._completions.last_kwargs is not None
    assert "max_tokens" not in fake._completions.last_kwargs


def test_content_json_fallback_parses(cache: LLMCache, cfg: SemanticConfig) -> None:
    raw = _raw_doc(["x"])
    payload = MagazineDoc(
        articles=[Article(title="Only", body="Body.")],
    ).model_dump_json()
    # parsed is None, but content carries the JSON — should parse and succeed.
    fake = FakeClient([FakeMessage(parsed=None, content=payload)])
    result = extract_semantic(raw, cfg, cache, client_factory=lambda _c: fake)
    assert len(result.articles) == 1
    assert result.articles[0].title == "Only"

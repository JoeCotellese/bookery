# ABOUTME: Integration test for core.pdf_converter — synthetic PDF + mocked semantic LLM.

from pathlib import Path
from typing import Any

import pytest

from bookery.convert import preflight
from bookery.convert.types import Article, MagazineDoc
from bookery.core.pdf_converter import convert_pdf
from tests.fixtures.pdf_factory import write_text_pdf


class _FakeMessage:
    def __init__(self, parsed: MagazineDoc) -> None:
        self.content = ""
        self.parsed = parsed


class _FakeChoice:
    def __init__(self, parsed: MagazineDoc) -> None:
        self.message = _FakeMessage(parsed)


class _FakeResponse:
    def __init__(self, parsed: MagazineDoc) -> None:
        self.choices = [_FakeChoice(parsed)]


class _FakeCompletions:
    def __init__(self, doc: MagazineDoc) -> None:
        self._doc = doc

    def parse(self, **_kwargs: Any) -> _FakeResponse:
        return _FakeResponse(self._doc)


class _FakeClient:
    def __init__(self, doc: MagazineDoc) -> None:
        self.beta = type(
            "B", (), {"chat": type("C", (), {"completions": _FakeCompletions(doc)})()}
        )()


@pytest.fixture
def _stub_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "check_llm", lambda *a, **k: None)
    monkeypatch.setattr(preflight, "check_pdf", lambda *a, **k: None)


def test_convert_pdf_happy_path(
    tmp_path: Path,
    _stub_preflight: None,
) -> None:
    pdf = write_text_pdf(
        tmp_path / "book.pdf",
        [
            ["Chapter One", "First paragraph here.", "Second paragraph here."],
            ["More prose continues on page two.", "And one more."],
        ],
    )

    out_dir = tmp_path / "out"
    data_dir = tmp_path / "data"

    doc = MagazineDoc(
        articles=[
            Article(title="Chapter One", body="First paragraph.\n\nSecond paragraph."),
            Article(title="Chapter Two", body="Page two prose."),
        ]
    )

    result = convert_pdf(
        pdf,
        out_dir,
        data_dir=data_dir,
        client_factory=lambda _cfg: _FakeClient(doc),
    )

    assert result.epub_path.exists()
    assert result.epub_path.suffix == ".epub"
    assert (data_dir / "convert_cache.db").exists()

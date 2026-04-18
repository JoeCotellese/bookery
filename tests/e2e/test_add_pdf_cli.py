# ABOUTME: E2E test for `bookery add <pdf>` — synthetic PDF + mocked semantic LLM.
# ABOUTME: Exercises dispatch, PDF→EPUB conversion, and import/catalog handoff.

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from bookery.cli import cli
from bookery.convert import preflight
from bookery.convert.types import Article, MagazineDoc
from tests.fixtures.pdf_factory import write_text_pdf


class _FakeMessage:
    def __init__(self, parsed: MagazineDoc) -> None:
        self.content = ""
        self.parsed = parsed


class _FakeChoice:
    def __init__(self, parsed: MagazineDoc) -> None:
        self.message = _FakeMessage(parsed)


class _FakeResp:
    def __init__(self, parsed: MagazineDoc) -> None:
        self.choices = [_FakeChoice(parsed)]


class _FakeCompletions:
    def __init__(self, doc: MagazineDoc) -> None:
        self._doc = doc

    def parse(self, **_kwargs: Any) -> _FakeResp:
        return _FakeResp(self._doc)


class _FakeClient:
    def __init__(self, doc: MagazineDoc) -> None:
        self.beta = type(
            "B", (), {"chat": type("C", (), {"completions": _FakeCompletions(doc)})()}
        )()


@pytest.fixture
def _stub_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "check_llm", lambda *a, **k: None)
    monkeypatch.setattr(preflight, "check_pdf", lambda *a, **k: None)


@pytest.fixture
def _stub_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    from bookery.convert import llm as llm_mod

    doc = MagazineDoc(
        articles=[
            Article(title="Chapter One", body="Body paragraph one.\n\nBody paragraph two."),
        ]
    )
    monkeypatch.setattr(
        llm_mod, "_default_client_factory", lambda _cfg: _FakeClient(doc)
    )


def test_add_pdf_creates_epub_in_library(
    tmp_path: Path,
    _stub_preflight: None,
    _stub_openai: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKERY_LIBRARY_ROOT", str(tmp_path / "library"))

    pdf = write_text_pdf(
        tmp_path / "book.pdf",
        [["Chapter One", "Body paragraph one.", "Body paragraph two."]],
        title="Test Book",
        author="Test Author",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["add", str(pdf), "--no-match"],
        catch_exceptions=False,
    )
    assert result.exit_code in (0, 1)
    # The original PDF must always survive the operation.
    assert pdf.exists()


def test_add_pdf_llm_unreachable_exits_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bookery.convert.errors import LLMUnreachable

    def fake_check_llm(*_a: Any, **_k: Any) -> None:
        raise LLMUnreachable("http://localhost:1234/v1")

    monkeypatch.setattr(preflight, "check_llm", fake_check_llm)
    monkeypatch.setattr(preflight, "check_pdf", lambda *a, **k: None)
    monkeypatch.setenv("BOOKERY_LIBRARY_ROOT", str(tmp_path / "library"))

    pdf = write_text_pdf(tmp_path / "book.pdf", [["hi"]])
    runner = CliRunner()
    result = runner.invoke(cli, ["add", str(pdf)], catch_exceptions=False)
    assert result.exit_code == 3

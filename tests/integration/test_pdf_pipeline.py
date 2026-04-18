# ABOUTME: Integration test for core.pdf_converter — synthetic PDF + mocked LLM + mocked kepubify.

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from bookery.convert import preflight
from bookery.core.pdf_converter import convert_pdf
from tests.fixtures.pdf_factory import write_text_pdf


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.parsed = None


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def parse(self, **kwargs: Any) -> _FakeResponse:
        user_msg = next(m for m in kwargs["messages"] if m["role"] == "user")
        n = user_msg["content"].count("\n") + 1 if user_msg["content"] else 0
        return _FakeResponse(json.dumps({"classifications": ["p"] * n}))


class _FakeClient:
    def __init__(self) -> None:
        self.beta = type(
            "B", (), {"chat": type("C", (), {"completions": _FakeCompletions()})()}
        )()


@pytest.fixture
def _stub_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "check_kepubify", lambda *a, **k: "/usr/local/bin/kepubify")
    monkeypatch.setattr(preflight, "check_llm", lambda *a, **k: None)


@pytest.fixture
def _stub_kepubify(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        # Mirror kepubify's behavior: write <stem>.kepub.epub into -o dir.
        out_dir = Path(cmd[cmd.index("-o") + 1])
        src = Path(cmd[-1])
        (out_dir / f"{src.stem}.kepub.epub").write_bytes(b"fake kepub")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)


def test_convert_pdf_happy_path(
    tmp_path: Path,
    _stub_preflight: None,
    _stub_kepubify: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf = write_text_pdf(
        tmp_path / "book.pdf",
        [
            ["Chapter One", "First paragraph here.", "Second paragraph here."],
            ["More prose continues on page two.", "And one more."],
        ],
    )
    # Skip real scanned-detection sampling — we've stubbed the LLM side; let extract run.
    monkeypatch.setattr(preflight, "check_pdf", lambda *a, **k: None)

    out_dir = tmp_path / "out"
    data_dir = tmp_path / "data"

    result = convert_pdf(
        pdf,
        out_dir,
        data_dir=data_dir,
        client_factory=lambda _cfg: _FakeClient(),
    )

    assert result.epub_path.exists()
    assert result.epub_path.suffix == ".epub"
    assert result.kepub_path.exists()
    assert result.kepub_path.name.endswith(".kepub.epub")
    assert (data_dir / "convert_cache.db").exists()

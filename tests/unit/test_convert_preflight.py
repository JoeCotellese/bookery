# ABOUTME: Unit tests for convert.preflight — kepubify, LM Studio, PDF encryption/scanned checks.

from pathlib import Path
from typing import Any

import httpx
import pytest

from bookery.convert import preflight
from bookery.convert.errors import (
    KepubifyMissing,
    LLMUnreachable,
    PdfEncrypted,
    PdfScanned,
)
from tests.fixtures.pdf_factory import write_blank_pdf, write_text_pdf


def test_check_kepubify_found() -> None:
    path = preflight.check_kepubify(which=lambda name: "/usr/local/bin/" + name)
    assert path == "/usr/local/bin/kepubify"


def test_check_kepubify_missing() -> None:
    with pytest.raises(KepubifyMissing):
        preflight.check_kepubify(which=lambda _name: None)


def test_check_llm_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, timeout: float) -> httpx.Response:
        assert url.endswith("/models")
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    preflight.check_llm("http://localhost:1234/v1")


def test_check_llm_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(LLMUnreachable):
        preflight.check_llm("http://localhost:1234/v1")


def test_check_llm_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, timeout: float) -> httpx.Response:
        return httpx.Response(500)

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(LLMUnreachable):
        preflight.check_llm("http://localhost:1234/v1")


def test_check_pdf_happy_path(tmp_path: Path) -> None:
    pdf = write_text_pdf(
        tmp_path / "book.pdf",
        [
            ["This is page one of the book with meaningful text content here."] * 5
            for _ in range(3)
        ],
    )
    preflight.check_pdf(pdf)


def test_check_pdf_scanned(tmp_path: Path) -> None:
    pdf = write_blank_pdf(tmp_path / "scan.pdf", page_count=3)
    with pytest.raises(PdfScanned):
        preflight.check_pdf(pdf)


def test_check_pdf_encrypted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = write_text_pdf(tmp_path / "enc.pdf", [["hello world"]])

    class FakeReader:
        is_encrypted = True

        def __init__(self, _path: Any) -> None:
            pass

    monkeypatch.setattr(preflight.pypdf, "PdfReader", FakeReader)
    with pytest.raises(PdfEncrypted):
        preflight.check_pdf(pdf)

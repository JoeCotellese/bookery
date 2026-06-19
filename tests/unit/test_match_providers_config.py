# ABOUTME: Tests that [matching].providers drives provider composition via build_metadata_provider.
# ABOUTME: Covers single-provider passthrough and multi-provider ConsensusProvider wrapping.

from pathlib import Path

from bookery.cli._match_helpers import build_active_providers, build_metadata_provider
from bookery.core.config import get_matching_config
from bookery.metadata.googlebooks import GoogleBooksProvider


def _install_config(home: Path, body: str | None) -> None:
    bookery_dir = home / ".bookery"
    bookery_dir.mkdir(parents=True, exist_ok=True)
    if body is not None:
        (bookery_dir / "config.toml").write_text(body)


def _isolate(monkeypatch, tmp_path, body: str | None = None) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("BOOKERY_LIBRARY_ROOT", raising=False)
    # Force Path.home() to honor our test HOME across platforms.
    monkeypatch.setattr(Path, "home", lambda: Path(str(tmp_path)))
    _install_config(tmp_path, body)


def test_default_config_returns_openlibrary_provider(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path, body=None)
    provider = build_metadata_provider(use_cache=False)
    assert type(provider).__name__ == "OpenLibraryProvider"


def test_multi_provider_config_wraps_in_consensus(monkeypatch, tmp_path) -> None:
    _isolate(
        monkeypatch,
        tmp_path,
        body='[matching]\nproviders = ["openlibrary", "googlebooks"]\n',
    )
    provider = build_metadata_provider(use_cache=False)
    assert type(provider).__name__ == "ConsensusProvider"
    assert provider.name == "consensus:openlibrary+googlebooks"


def test_googlebooks_only_config(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path, body='[matching]\nproviders = ["googlebooks"]\n')
    provider = build_metadata_provider(use_cache=False)
    assert type(provider).__name__ == "GoogleBooksProvider"


def test_googlebooks_reads_api_key_from_env(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path, body='[matching]\nproviders = ["googlebooks"]\n')
    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "env-key-123")
    provider = build_metadata_provider(use_cache=False)
    assert isinstance(provider, GoogleBooksProvider)
    assert provider._api_key == "env-key-123"


def test_googlebooks_without_api_key_env_is_none(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path, body='[matching]\nproviders = ["googlebooks"]\n')
    monkeypatch.delenv("GOOGLE_BOOKS_API_KEY", raising=False)
    provider = build_metadata_provider(use_cache=False)
    assert isinstance(provider, GoogleBooksProvider)
    assert provider._api_key is None


def test_matching_config_parses_min_request_interval(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path, body="[matching]\nmin_request_interval = 0.5\n")
    assert get_matching_config().min_request_interval == 0.5


def test_matching_config_min_request_interval_defaults(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path, body=None)
    assert get_matching_config().min_request_interval == 0.1


def test_http_client_uses_configured_interval(monkeypatch, tmp_path) -> None:
    _isolate(
        monkeypatch,
        tmp_path,
        body='[matching]\nproviders = ["openlibrary"]\nmin_request_interval = 2.0\n',
    )
    captured: list[float] = []

    class _CapturingClient:
        def __init__(self, *, min_request_interval: float = 0.1, **_: object) -> None:
            captured.append(min_request_interval)

    monkeypatch.setattr("bookery.metadata.http.BookeryHttpClient", _CapturingClient)
    build_active_providers(use_cache=False)
    assert captured == [2.0]


def test_unknown_provider_is_skipped(monkeypatch, tmp_path) -> None:
    _isolate(
        monkeypatch,
        tmp_path,
        body='[matching]\nproviders = ["bogus", "openlibrary"]\n',
    )
    provider = build_metadata_provider(use_cache=False)
    assert type(provider).__name__ == "OpenLibraryProvider"

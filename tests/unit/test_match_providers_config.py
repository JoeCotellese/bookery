# ABOUTME: Tests that [matching].providers drives provider composition via build_metadata_provider.
# ABOUTME: Covers single-provider passthrough and multi-provider ConsensusProvider wrapping.

from pathlib import Path

from bookery.cli._match_helpers import build_metadata_provider
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


def test_unknown_provider_is_skipped(monkeypatch, tmp_path) -> None:
    _isolate(
        monkeypatch,
        tmp_path,
        body='[matching]\nproviders = ["bogus", "openlibrary"]\n',
    )
    provider = build_metadata_provider(use_cache=False)
    assert type(provider).__name__ == "OpenLibraryProvider"

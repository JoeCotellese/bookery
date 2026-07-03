# ABOUTME: Unit tests for the metadata provider registry (issue #286).
# ABOUTME: Verifies built-in factories and that build_active_providers consumes the registry.

from pathlib import Path

from bookery.metadata.googlebooks import GoogleBooksProvider
from bookery.metadata.openlibrary import OpenLibraryProvider
from bookery.metadata.provider import MetadataProvider
from bookery.metadata.registry import PROVIDER_FACTORIES, ProviderContext


class _StubHttpClient:
    def get(self, url, params=None):
        return {}


def _ctx() -> ProviderContext:
    return ProviderContext(http_client_for=lambda name: _StubHttpClient())


class TestProviderFactories:
    def test_builtin_keys(self) -> None:
        assert set(PROVIDER_FACTORIES) == {"openlibrary", "googlebooks"}

    def test_openlibrary_factory_builds_provider(self) -> None:
        provider = PROVIDER_FACTORIES["openlibrary"](_ctx())
        assert isinstance(provider, OpenLibraryProvider)

    def test_googlebooks_factory_builds_provider(self) -> None:
        provider = PROVIDER_FACTORIES["googlebooks"](_ctx())
        assert isinstance(provider, GoogleBooksProvider)

    def test_googlebooks_factory_reads_api_key_env(self, monkeypatch) -> None:
        monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "registry-key")
        provider = PROVIDER_FACTORIES["googlebooks"](_ctx())
        assert isinstance(provider, GoogleBooksProvider)
        assert provider._api_key == "registry-key"

    def test_googlebooks_factory_without_api_key_env(self, monkeypatch) -> None:
        monkeypatch.delenv("GOOGLE_BOOKS_API_KEY", raising=False)
        provider = PROVIDER_FACTORIES["googlebooks"](_ctx())
        assert isinstance(provider, GoogleBooksProvider)
        assert provider._api_key is None


class TestRegistryDrivesBuildActiveProviders:
    def test_registered_fake_factory_round_trips(self, monkeypatch, tmp_path) -> None:
        """A factory added to the registry is buildable straight from config."""
        from bookery.cli._match_helpers import build_active_providers

        class FakeProvider:
            name = "Fake Source"

            def search_by_isbn(self, isbn):
                return []

            def search_by_title_author(self, title, author=None):
                return []

            def lookup_by_url(self, url):
                return None

        built_with: list[ProviderContext] = []

        def fake_factory(ctx: ProviderContext) -> MetadataProvider:
            built_with.append(ctx)
            return FakeProvider()

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(Path, "home", lambda: Path(str(tmp_path)))
        bookery_dir = tmp_path / ".bookery"
        bookery_dir.mkdir(parents=True, exist_ok=True)
        (bookery_dir / "config.toml").write_text('[matching]\nproviders = ["fakesource"]\n')

        monkeypatch.setitem(PROVIDER_FACTORIES, "fakesource", fake_factory)

        providers = build_active_providers(use_cache=False)

        assert list(providers) == ["fakesource"]
        assert isinstance(providers["fakesource"], FakeProvider)
        assert len(built_with) == 1
        assert callable(built_with[0].http_client_for)

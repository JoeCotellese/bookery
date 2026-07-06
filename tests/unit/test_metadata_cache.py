# ABOUTME: Unit tests for MetadataCache and CachingHttpClient.
# ABOUTME: Verifies SQLite round-trip, TTL expiry, per-provider scoping, and HTTP wrapping.

import time
from pathlib import Path
from typing import Any

import pytest

from bookery.metadata.cache import MetadataCache
from bookery.metadata.http import CachingHttpClient


class _RecordingClient:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, tuple[tuple[str, str], ...] | None]] = []

    def get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        self.calls.append((url, tuple(sorted(params.items())) if params else None))
        return self._responses[url]


class TestMetadataCache:
    def test_put_then_get_returns_response(self, tmp_path: Path) -> None:
        cache = MetadataCache(tmp_path / "c.db", ttl_seconds=60)
        cache.put("openlibrary", "/isbn/X.json", "key1", {"a": 1})
        assert cache.get("openlibrary", "/isbn/X.json", "key1") == {"a": 1}

    def test_miss_returns_none(self, tmp_path: Path) -> None:
        cache = MetadataCache(tmp_path / "c.db", ttl_seconds=60)
        assert cache.get("openlibrary", "/x", "k") is None

    def test_ttl_expiry(self, tmp_path: Path) -> None:
        cache = MetadataCache(tmp_path / "c.db", ttl_seconds=0.01)
        cache.put("openlibrary", "/x", "k", {"a": 1})
        time.sleep(0.05)
        assert cache.get("openlibrary", "/x", "k") is None

    def test_provider_scoping(self, tmp_path: Path) -> None:
        cache = MetadataCache(tmp_path / "c.db", ttl_seconds=60)
        cache.put("openlibrary", "/x", "k", {"who": "ol"})
        cache.put("googlebooks", "/x", "k", {"who": "gb"})
        assert cache.get("openlibrary", "/x", "k") == {"who": "ol"}
        assert cache.get("googlebooks", "/x", "k") == {"who": "gb"}

    def test_clear_scoped_by_provider(self, tmp_path: Path) -> None:
        cache = MetadataCache(tmp_path / "c.db", ttl_seconds=60)
        cache.put("openlibrary", "/x", "k", {"v": 1})
        cache.put("googlebooks", "/x", "k", {"v": 2})
        cache.clear(provider="openlibrary")
        assert cache.get("openlibrary", "/x", "k") is None
        assert cache.get("googlebooks", "/x", "k") == {"v": 2}


class TestCachingHttpClient:
    def test_second_call_is_served_from_cache(self, tmp_path: Path) -> None:
        inner = _RecordingClient({"https://example.com/a": {"ok": True}})
        cache = MetadataCache(tmp_path / "c.db", ttl_seconds=60)
        client = CachingHttpClient(inner, cache, provider="openlibrary")

        first = client.get("https://example.com/a")
        second = client.get("https://example.com/a")

        assert first == second == {"ok": True}
        assert len(inner.calls) == 1

    def test_params_part_of_cache_key(self, tmp_path: Path) -> None:
        inner = _RecordingClient({"https://example.com/s": {"ok": True}})
        cache = MetadataCache(tmp_path / "c.db", ttl_seconds=60)
        client = CachingHttpClient(inner, cache, provider="openlibrary")

        client.get("https://example.com/s", {"q": "a"})
        client.get("https://example.com/s", {"q": "b"})

        # Different params = different cache entries → two upstream calls
        assert len(inner.calls) == 2

    def test_expired_entry_triggers_refresh(self, tmp_path: Path) -> None:
        inner = _RecordingClient({"https://example.com/a": {"ok": True}})
        cache = MetadataCache(tmp_path / "c.db", ttl_seconds=0.01)
        client = CachingHttpClient(inner, cache, provider="openlibrary")

        client.get("https://example.com/a")
        time.sleep(0.05)
        client.get("https://example.com/a")

        assert len(inner.calls) == 2

    def test_missing_response_propagates_keyerror(self, tmp_path: Path) -> None:
        inner = _RecordingClient({})
        cache = MetadataCache(tmp_path / "c.db", ttl_seconds=60)
        client = CachingHttpClient(inner, cache, provider="openlibrary")
        with pytest.raises(KeyError):
            client.get("https://example.com/missing")


class _RecordingPostClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.calls: list[tuple[str, dict[str, Any], dict[str, str] | None]] = []

    def post_json(
        self,
        url: str,
        json_body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((url, json_body, headers))
        return self._response


class TestCachingHttpClientPostJson:
    def test_identical_body_served_from_cache(self, tmp_path: Path) -> None:
        inner = _RecordingPostClient({"data": {"books": []}})
        cache = MetadataCache(tmp_path / "c.db", ttl_seconds=60)
        client = CachingHttpClient(inner, cache, provider="hardcover")

        body = {"query": "{ books }", "variables": {"isbn": "978"}}
        first = client.post_json("https://api.example.com/v1/graphql", body)
        second = client.post_json("https://api.example.com/v1/graphql", body)

        assert first == second == {"data": {"books": []}}
        assert len(inner.calls) == 1

    def test_different_variables_miss_cache(self, tmp_path: Path) -> None:
        inner = _RecordingPostClient({"data": 1})
        cache = MetadataCache(tmp_path / "c.db", ttl_seconds=60)
        client = CachingHttpClient(inner, cache, provider="hardcover")

        client.post_json("https://api.example.com/v1/graphql", {"variables": {"isbn": "1"}})
        client.post_json("https://api.example.com/v1/graphql", {"variables": {"isbn": "2"}})

        assert len(inner.calls) == 2

    def test_auth_headers_not_part_of_cache_key(self, tmp_path: Path) -> None:
        inner = _RecordingPostClient({"data": 1})
        cache = MetadataCache(tmp_path / "c.db", ttl_seconds=60)
        client = CachingHttpClient(inner, cache, provider="hardcover")

        body = {"query": "{ x }"}
        url = "https://api.example.com/v1/graphql"
        client.post_json(url, body, headers={"Authorization": "Bearer a"})
        client.post_json(url, body, headers={"Authorization": "Bearer b"})

        assert len(inner.calls) == 1

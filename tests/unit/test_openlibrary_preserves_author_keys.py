# ABOUTME: Verifies that OpenLibraryProvider._lookup_by_works preserves openlibrary_author_keys.
# ABOUTME: Regression guard against the old behavior of deleting author OLIDs after resolution.

from typing import Any

from bookery.metadata.openlibrary import OpenLibraryProvider


class _StubHttpClient:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self._responses = responses

    def get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        # Strip host for lookup convenience
        key = url.replace("https://openlibrary.org", "")
        return self._responses[key]


def test_lookup_by_works_keeps_author_keys_in_identifiers() -> None:
    http = _StubHttpClient(
        {
            "/works/OL1W.json": {
                "key": "/works/OL1W",
                "title": "T",
                "authors": [{"author": {"key": "/authors/OL1A"}}],
            },
            "/authors/OL1A.json": {"name": "Author Name"},
        }
    )
    provider = OpenLibraryProvider(http_client=http)
    candidate = provider._lookup_by_works("/works/OL1W")

    assert candidate.metadata.authors == ["Author Name"]
    assert candidate.metadata.identifiers.get("openlibrary_author_keys") == "/authors/OL1A"

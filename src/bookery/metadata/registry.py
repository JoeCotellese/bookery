# ABOUTME: Name→factory registry for metadata providers.
# ABOUTME: Add new in-tree providers here; build_active_providers consumes this mapping.

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bookery.metadata.googlebooks import GoogleBooksProvider
from bookery.metadata.openlibrary import OpenLibraryProvider
from bookery.metadata.provider import MetadataProvider


@dataclass(frozen=True)
class ProviderContext:
    """Dependencies handed to provider factories.

    ``http_client_for(provider_name)`` returns an HTTP client namespaced for
    caching/throttling. It is built by the caller (where config lives) so
    factories stay free of cache and rate-limit wiring.
    """

    http_client_for: Callable[[str], Any]


def _make_openlibrary(ctx: ProviderContext) -> MetadataProvider:
    return OpenLibraryProvider(http_client=ctx.http_client_for("openlibrary"))


def _make_googlebooks(ctx: ProviderContext) -> MetadataProvider:
    return GoogleBooksProvider(
        http_client=ctx.http_client_for("googlebooks"),
        api_key=os.environ.get("GOOGLE_BOOKS_API_KEY"),
    )


# Registry consumed by cli/_match_helpers.build_active_providers. Keys are the
# names accepted in [matching].providers. ponytail: plain dict, no entry-point
# or pluggy loading — add that only when an out-of-tree provider exists.
PROVIDER_FACTORIES: dict[str, Callable[[ProviderContext], MetadataProvider]] = {
    "openlibrary": _make_openlibrary,
    "googlebooks": _make_googlebooks,
}

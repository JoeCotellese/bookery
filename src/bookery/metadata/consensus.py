# ABOUTME: Consensus metadata provider that merges results from multiple providers.
# ABOUTME: Prefers values agreed on by ≥2 providers; otherwise falls back to priority order.

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields as dataclass_fields
from typing import Any

from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.provider import MetadataProvider
from bookery.metadata.types import BookMetadata

logger = logging.getLogger(__name__)

_SCALAR_FIELDS = (
    "title",
    "subtitle",
    "author_sort",
    "language",
    "publisher",
    "isbn",
    "description",
    "series",
    "series_index",
    "cover_url",
    "published_date",
    "original_publication_date",
    "page_count",
    "rating",
    "ratings_count",
    "print_type",
    "maturity_rating",
)
_LIST_FIELDS = ("authors", "subjects")
_AGREEMENT_BONUS = 0.05


def _normalize_isbn(isbn: str | None) -> str | None:
    if not isbn:
        return None
    return "".join(ch for ch in isbn if ch.isalnum()).upper() or None


def _normalize_for_vote(field_name: str, value: Any) -> Any:
    """Turn a field value into a hashable key used to count agreement."""
    if value is None:
        return None
    if field_name == "isbn":
        return _normalize_isbn(value)
    if isinstance(value, str):
        return value.strip().casefold() or None
    if isinstance(value, list):
        return tuple(
            item.strip().casefold()
            for item in value
            if isinstance(item, str) and item.strip()
        )
    return value


def _pick_scalar(
    field_name: str,
    values: list[tuple[str, Any]],
    provenance: dict[str, str],
) -> Any:
    """Pick a value for a scalar field from (provider, value) pairs.

    values is in priority order. Prefer values agreed on by ≥2 providers,
    otherwise the first non-empty value. Records which provider supplied
    the chosen value in ``provenance``.
    """
    non_empty = [(p, v) for p, v in values if v not in (None, "", [])]
    if not non_empty:
        return None

    counts: Counter[Any] = Counter()
    key_to_first: dict[Any, tuple[str, Any]] = {}
    for provider, value in non_empty:
        key = _normalize_for_vote(field_name, value)
        if key is None:
            continue
        counts[key] += 1
        if key not in key_to_first:
            key_to_first[key] = (provider, value)

    if counts:
        top_key, top_count = counts.most_common(1)[0]
        if top_count >= 2:
            provider, value = key_to_first[top_key]
            provenance[field_name] = provider
            return value

    provider, value = non_empty[0]
    provenance[field_name] = provider
    return value


def _pick_list(
    field_name: str,
    values: list[tuple[str, list[str]]],
    provenance: dict[str, str],
) -> list[str]:
    """Pick a list field (authors, subjects): agreement wins, else priority order."""
    non_empty = [(p, v) for p, v in values if v]
    if not non_empty:
        return []

    counts: Counter[tuple[str, ...]] = Counter()
    key_to_first: dict[tuple[str, ...], tuple[str, list[str]]] = {}
    for provider, value in non_empty:
        key = _normalize_for_vote(field_name, value)
        if not isinstance(key, tuple) or not key:
            continue
        counts[key] += 1
        if key not in key_to_first:
            key_to_first[key] = (provider, value)

    if counts:
        top_key, top_count = counts.most_common(1)[0]
        if top_count >= 2:
            provider, value = key_to_first[top_key]
            provenance[field_name] = provider
            return list(value)

    provider, value = non_empty[0]
    provenance[field_name] = provider
    return list(value)


def _merge(
    per_provider: list[tuple[str, BookMetadata]],
) -> tuple[BookMetadata, dict[str, str]]:
    """Merge per-provider metadata. Returns (merged, provenance_by_field)."""
    provenance: dict[str, str] = {}

    merged_identifiers: dict[str, str] = {}
    for _provider, meta in per_provider:
        for k, v in meta.identifiers.items():
            merged_identifiers.setdefault(k, v)

    kwargs: dict[str, Any] = {"identifiers": merged_identifiers}

    title_values = [
        (p, m.title if m.title and m.title != "Unknown" else None)
        for p, m in per_provider
    ]
    kwargs["title"] = _pick_scalar("title", title_values, provenance) or per_provider[0][1].title

    for fname in _SCALAR_FIELDS:
        if fname == "title":
            continue
        values = [(p, getattr(m, fname)) for p, m in per_provider]
        kwargs[fname] = _pick_scalar(fname, values, provenance)

    for fname in _LIST_FIELDS:
        values = [(p, getattr(m, fname)) for p, m in per_provider]
        kwargs[fname] = _pick_list(fname, values, provenance)

    # Cover image (bytes) and source_path aren't provider-sourced here — preserve first non-None.
    for fname in ("cover_image", "source_path"):
        for _p, meta in per_provider:
            val = getattr(meta, fname)
            if val is not None:
                kwargs[fname] = val
                break

    # Only keep keys that BookMetadata actually defines (defensive).
    allowed = {f.name for f in dataclass_fields(BookMetadata)}
    kwargs = {k: v for k, v in kwargs.items() if k in allowed}

    return BookMetadata(**kwargs), provenance


class ConsensusProvider:
    """Merges candidates from multiple providers into a single candidate.

    Strategy:
      * Query all providers (in parallel via a thread pool).
      * For each candidate field, prefer the value agreed on by ≥2 providers;
        otherwise fall back to the first provider in ``providers`` priority order.
      * When ≥2 providers return a matching ISBN, bump confidence.
      * Per-field provider attribution is stashed in ``metadata.identifiers``
        under ``provenance_<field>`` so downstream code (issue #89) can record it.
    """

    def __init__(self, providers: list[MetadataProvider]) -> None:
        if not providers:
            msg = "ConsensusProvider requires at least one provider"
            raise ValueError(msg)
        self._providers = providers

    @property
    def name(self) -> str:
        return "consensus:" + "+".join(p.name for p in self._providers)

    def search_by_isbn(self, isbn: str) -> list[MetadataCandidate]:
        per_provider = self._run_parallel(
            lambda p: p.search_by_isbn(isbn)
        )
        return self._merge_top(per_provider)

    def search_by_title_author(
        self, title: str, author: str | None = None
    ) -> list[MetadataCandidate]:
        per_provider = self._run_parallel(
            lambda p: p.search_by_title_author(title, author)
        )
        return self._merge_top(per_provider)

    def lookup_by_url(self, url: str) -> MetadataCandidate | None:
        for provider in self._providers:
            candidate = provider.lookup_by_url(url)
            if candidate is not None:
                return candidate
        return None

    def _run_parallel(
        self,
        fn: Any,
    ) -> list[tuple[str, list[MetadataCandidate]]]:
        """Run fn(provider) for each provider, in parallel."""
        if len(self._providers) == 1:
            return [(self._providers[0].name, fn(self._providers[0]))]

        results: list[tuple[str, list[MetadataCandidate]]] = []
        with ThreadPoolExecutor(max_workers=len(self._providers)) as executor:
            futures = {
                executor.submit(fn, provider): provider for provider in self._providers
            }
            # Preserve priority order rather than completion order.
            provider_to_result: dict[str, list[MetadataCandidate]] = {}
            for future, provider in futures.items():
                try:
                    provider_to_result[provider.name] = future.result()
                except Exception as exc:
                    logger.warning(
                        "Provider %s failed: %s", provider.name, exc
                    )
                    provider_to_result[provider.name] = []
            for provider in self._providers:
                results.append((provider.name, provider_to_result.get(provider.name, [])))
        return results

    def _merge_top(
        self, per_provider_results: list[tuple[str, list[MetadataCandidate]]]
    ) -> list[MetadataCandidate]:
        top: list[tuple[str, BookMetadata]] = []
        max_conf = 0.0
        for provider_name, candidates in per_provider_results:
            if not candidates:
                continue
            top.append((provider_name, candidates[0].metadata))
            max_conf = max(max_conf, candidates[0].confidence)

        if not top:
            return []

        if len(top) == 1:
            provider_name, metadata = top[0]
            metadata.identifiers.setdefault("source", provider_name)
            return [
                MetadataCandidate(
                    metadata=metadata,
                    confidence=max_conf,
                    source=provider_name,
                    source_id=metadata.identifiers.get(
                        f"{provider_name}_volume",
                        metadata.identifiers.get(f"{provider_name}_work", "unknown"),
                    ),
                )
            ]

        merged, provenance = _merge(top)

        for field_name, provider_name in provenance.items():
            merged.identifiers[f"provenance_{field_name}"] = provider_name
        merged.identifiers["source"] = self.name

        confidence = max_conf
        isbns = [m.isbn for _p, m in top if m.isbn]
        if len(isbns) >= 2:
            normalized = {_normalize_isbn(i) for i in isbns}
            normalized.discard(None)
            if len(normalized) == 1:
                confidence = min(1.0, confidence + _AGREEMENT_BONUS)

        return [
            MetadataCandidate(
                metadata=merged,
                confidence=confidence,
                source=self.name,
                source_id=(
                    merged.isbn
                    or top[0][1].identifiers.get("openlibrary_work", "consensus")
                ),
            )
        ]

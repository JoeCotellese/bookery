# ABOUTME: Shared helpers for building match and progress callbacks.
# ABOUTME: Used by both `import` and `add` commands so behavior stays in one place.

from pathlib import Path

from rich.console import Console

from bookery.core.importer import ImportResult, MatchFn, MatchResult, ProgressFn
from bookery.metadata.types import BookMetadata


def build_metadata_provider(*, use_cache: bool = True):
    """Build the default metadata provider with optional response caching.

    When ``use_cache`` is true, wraps the HTTP client in a
    :class:`CachingHttpClient` backed by a SQLite cache at
    ``{data_dir}/metadata_cache.db`` with a TTL from
    ``[matching].cache_ttl_days``.
    """
    from bookery.core.config import get_data_dir, get_matching_config
    from bookery.metadata.cache import MetadataCache
    from bookery.metadata.http import BookeryHttpClient, CachingHttpClient
    from bookery.metadata.openlibrary import OpenLibraryProvider

    http_client: object = BookeryHttpClient()
    if use_cache:
        matching = get_matching_config()
        cache = MetadataCache(
            get_data_dir() / "metadata_cache.db",
            ttl_seconds=matching.cache_ttl_days * 86400.0,
        )
        http_client = CachingHttpClient(
            http_client,  # type: ignore[arg-type]
            cache,
            provider="openlibrary",
        )
    return OpenLibraryProvider(http_client=http_client)  # type: ignore[arg-type]


def build_match_fn(
    console: Console,
    output_dir: Path,
    quiet: bool,
    threshold: float,
    *,
    use_cache: bool = True,
) -> MatchFn:
    """Build a match callback that runs the full metadata pipeline.

    Imports match-pipeline dependencies lazily so callers don't pay for
    them when matching is not used.
    """
    from bookery.cli.review import ReviewSession
    from bookery.core.pipeline import match_one

    provider = build_metadata_provider(use_cache=use_cache)
    review = ReviewSession(
        console=console,
        quiet=quiet,
        threshold=threshold,
        lookup_fn=provider.lookup_by_url,
    )

    def match_fn(
        _extracted: BookMetadata, epub_path: Path,
    ) -> MatchResult | None:
        del _extracted  # signature required by MatchFn protocol
        result = match_one(epub_path, provider, review, output_dir)

        if not quiet and result.normalization and result.normalization.was_modified:
            console.print(
                f"  [dim]Normalized:[/dim] {result.normalization.normalized.title}"
            )

        if result.status == "matched" and result.metadata is not None:
            if not quiet:
                console.print(
                    f"  [green]Written:[/green] {result.output_path}"
                )
            return MatchResult(
                metadata=result.metadata, output_path=result.output_path,
            )

        if result.status == "error" and not quiet:
            console.print(
                f"  [red]Write failed:[/red] {result.error}"
            )

        return None

    return match_fn


def build_progress_fn(console: Console) -> ProgressFn:
    """Build a per-file progress callback for Rich console output."""

    def on_progress(
        path: Path,
        title: str,
        author: str,
        status: str,
        reason: str | None,
        existing_id: int | None,
    ) -> None:
        label = f"{title} — {author}" if title and author else path.name
        if status == "added":
            console.print(f"  [green]✓[/green] {label}")
        elif status == "skipped" and reason:
            reason_label = reason.replace("_", "+")
            id_suffix = f", #{existing_id}" if existing_id else ""
            console.print(
                f"  [yellow]⊘[/yellow] {label} — "
                f"[dim]skipped (duplicate: {reason_label}{id_suffix})[/dim]"
            )
        elif status == "forced" and reason:
            reason_label = reason.replace("_", "+")
            id_suffix = f", #{existing_id}" if existing_id else ""
            console.print(
                f"  [yellow]⚠[/yellow] {label} — "
                f"[dim]imported (duplicate: {reason_label}{id_suffix})[/dim]"
            )
        elif status == "error":
            console.print(f"  [red]✗[/red] {path.name} — [red]{reason}[/red]")
        elif status == "move_failed":
            console.print(
                f"  [yellow]⚠[/yellow] {path.name} — "
                f"[dim]cataloged but source not removed: {reason}[/dim]"
            )

    return on_progress


def format_skip_breakdown(result: ImportResult) -> str:
    """Format a skip count with breakdown by reason."""
    if result.skipped == 0:
        return ""

    parts = []
    if result.skipped_hash:
        parts.append(f"{result.skipped_hash} hash")
    if result.skipped_metadata:
        reason_counts: dict[str, int] = {}
        for detail in result.skip_details:
            if detail.reason in ("isbn", "title_author"):
                label = detail.reason.replace("_", "+")
                reason_counts[label] = reason_counts.get(label, 0) + 1
        parts.extend(f"{count} {reason}" for reason, count in reason_counts.items())

    breakdown = f" ({', '.join(parts)})" if parts else ""
    return f"{result.skipped} skipped{breakdown}"

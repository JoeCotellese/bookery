# ABOUTME: Interactive review session for metadata candidate selection.
# ABOUTME: Displays candidates in a Rich table and prompts the user to choose.

from collections.abc import Callable

import click
from rich.console import Console
from rich.table import Table

from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata


class ReviewSession:
    """Interactive review for metadata candidates.

    Displays current metadata and a table of candidates, then prompts
    the user to select one, skip, or keep the original.
    """

    def __init__(
        self,
        *,
        console: Console | None = None,
        quiet: bool = False,
        threshold: float = 0.8,
        lookup_fn: Callable[[str], MetadataCandidate | None] | None = None,
    ) -> None:
        self._console = console or Console()
        self._quiet = quiet
        self._threshold = threshold
        self._lookup_fn = lookup_fn

    def review(
        self, extracted: BookMetadata, candidates: list[MetadataCandidate]
    ) -> BookMetadata | None:
        """Present candidates for user review and return the chosen metadata.

        Returns:
            Selected BookMetadata, or None if the user skips.
        """
        if not candidates:
            return None

        # Quiet mode: auto-accept best candidate if above threshold
        if self._quiet:
            best = candidates[0]
            if best.confidence >= self._threshold:
                return best.metadata
            return None

        # Display current metadata
        self._console.print(f"\n[bold]Current:[/bold] {extracted.title}")
        if extracted.authors:
            self._console.print(f"  Author: {extracted.author}")

        # Display candidate table
        table = Table(title="Candidates")
        table.add_column("#", style="bold", width=3)
        table.add_column("Title")
        table.add_column("Author")
        table.add_column("ISBN")
        table.add_column("Language")
        table.add_column("OL ID", style="dim")
        table.add_column("Confidence", justify="right")
        table.add_column("Source")

        for i, candidate in enumerate(candidates, start=1):
            conf_pct = f"{candidate.confidence:.0%}"
            ol_id = candidate.source_id.removeprefix("/works/")
            table.add_row(
                str(i),
                candidate.metadata.title,
                candidate.metadata.author,
                candidate.metadata.isbn or "—",
                candidate.metadata.language or "—",
                ol_id,
                conf_pct,
                candidate.source,
            )

        self._console.print(table)

        # Prompt loop — supports direct selection and detail view
        prompt_parts = "[1-N] Accept  [v1-vN] View details"
        if self._lookup_fn is not None:
            prompt_parts += "  [u] URL lookup"
        prompt_parts += "  [s] Skip  [k] Keep original"

        while True:
            choice = click.prompt(prompt_parts, type=str, default="s")

            if choice.lower() == "s":
                return None
            if choice.lower() == "k":
                return extracted

            # URL lookup: u
            if choice.lower() == "u" and self._lookup_fn is not None:
                result = self._url_lookup_prompt(extracted)
                if result is not None:
                    return result
                continue

            # Detail view: v<N>
            if choice.lower().startswith("v"):
                try:
                    idx = int(choice[1:]) - 1
                    if 0 <= idx < len(candidates):
                        result = self._detail_prompt(
                            extracted, candidates[idx]
                        )
                        if result is not None:
                            return result
                        # result is None means "back to list"
                        continue
                except ValueError:
                    pass
                continue

            # Direct selection: <N>
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(candidates):
                    return candidates[idx].metadata
            except ValueError:
                pass

    def _show_detail(
        self,
        extracted: BookMetadata,
        candidate: MetadataCandidate,
    ) -> None:
        """Render a side-by-side comparison of current vs candidate metadata."""
        detail = Table(title="Detail Comparison")
        detail.add_column("Field", style="bold")
        detail.add_column("Current → Candidate")

        fields = [
            ("Title", extracted.title, candidate.metadata.title),
            ("Author", extracted.author, candidate.metadata.author),
            ("ISBN", extracted.isbn, candidate.metadata.isbn),
            ("Language", extracted.language, candidate.metadata.language),
            ("Publisher", extracted.publisher, candidate.metadata.publisher),
            ("Description", extracted.description, candidate.metadata.description),
        ]

        for label, current, proposed in fields:
            cur = current or "—"
            prop = proposed or "—"
            detail.add_row(label, f"{cur} → {prop}")

        self._console.print(detail)

    def _detail_prompt(
        self,
        extracted: BookMetadata,
        candidate: MetadataCandidate,
    ) -> BookMetadata | None:
        """Show detail view and prompt to accept or go back.

        Returns the candidate's metadata if accepted, or None to go back.
        """
        self._show_detail(extracted, candidate)

        detail_choice = click.prompt(
            "[a] Accept  [b] Back to list",
            type=str,
            default="b",
        )

        if detail_choice.lower() == "a":
            return candidate.metadata
        return None

    def _url_lookup_prompt(self, extracted: BookMetadata) -> BookMetadata | None:
        """Prompt for a URL, look up metadata, and show detail view.

        Returns the candidate's metadata if accepted, or None to go back.
        """
        url = click.prompt("Enter Open Library URL", type=str)
        assert self._lookup_fn is not None
        candidate = self._lookup_fn(url)
        if candidate is None:
            self._console.print("[red]Could not fetch metadata from URL.[/red]")
            return None

        return self._detail_prompt(extracted, candidate)

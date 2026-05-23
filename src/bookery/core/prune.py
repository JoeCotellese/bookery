# ABOUTME: Orphan-row detection for `bookery prune`.
# ABOUTME: Classifies catalog rows by on-disk presence of source_path and output_path.

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from bookery.db.catalog import LibraryCatalog
from bookery.db.mapping import BookRecord

CheckMode = Literal["source", "output", "both"]


class PruneState(StrEnum):
    """The disposition of a single catalog row under a prune walk."""

    HEALTHY = "healthy"
    ORPHAN = "orphan"
    SOURCE_MISSING_OUTPUT_PRESENT = "source-missing-output-present"


@dataclass(frozen=True, slots=True)
class PruneCandidate:
    """A single row's prune classification.

    Bundles the record alongside the two on-disk existence flags so the
    CLI layer can render a table without re-stat'ing files.
    """

    record: BookRecord
    source_exists: bool
    output_exists: bool
    state: PruneState


def classify_row(
    record: BookRecord, *, check: CheckMode
) -> PruneCandidate:
    """Classify a single catalog row by on-disk presence.

    The ``check`` flag controls which paths participate in the orphan
    decision:

    - ``source``: a row is an orphan iff its ``source_path`` is missing.
    - ``output``: a row is an orphan iff its ``output_path`` is missing
      (rows with no ``output_path`` set are treated as healthy under this
      mode — there's nothing to check).
    - ``both``: a row is an orphan only when every path under
      consideration is missing. A row whose source is gone but whose
      output is still on disk is flagged
      ``SOURCE_MISSING_OUTPUT_PRESENT`` — a future flag will let the
      operator rewrite ``source_path`` instead of deleting the row.
    """
    source_exists = record.source_path.exists()
    output_exists = (
        record.output_path.exists() if record.output_path is not None else False
    )

    if check == "source":
        state = PruneState.HEALTHY if source_exists else PruneState.ORPHAN
    elif check == "output":
        if record.output_path is None:
            state = PruneState.HEALTHY
        else:
            state = PruneState.HEALTHY if output_exists else PruneState.ORPHAN
    else:  # both
        if not source_exists and (record.output_path is None or not output_exists):
            state = PruneState.ORPHAN
        elif not source_exists and output_exists:
            state = PruneState.SOURCE_MISSING_OUTPUT_PRESENT
        else:
            state = PruneState.HEALTHY

    return PruneCandidate(
        record=record,
        source_exists=source_exists,
        output_exists=output_exists,
        state=state,
    )


def classify_catalog(
    catalog: LibraryCatalog, *, check: CheckMode
) -> list[PruneCandidate]:
    """Walk every catalog row and classify each one.

    Healthy rows are omitted — only orphans and the source-missing
    warning state are returned, in catalog order.
    """
    candidates: list[PruneCandidate] = []
    for record in catalog.list_all():
        candidate = classify_row(record, check=check)
        if candidate.state is PruneState.HEALTHY:
            continue
        candidates.append(candidate)
    return candidates

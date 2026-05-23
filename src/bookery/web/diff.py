# ABOUTME: Field-by-field BookMetadata diff helper for the apply-candidate flow.
# ABOUTME: Produces FieldDiff rows the diff template renders as current vs proposed.

from __future__ import annotations

from dataclasses import dataclass

from bookery.metadata.types import BookMetadata


@dataclass(frozen=True)
class FieldDiff:
    """A single row of the metadata diff.

    ``current`` and ``proposed`` are pre-formatted display strings (empty
    string when the underlying value is None/missing). ``changed`` collapses
    None/empty equivalence and ordered-list comparison so templates can
    branch on a single boolean. ``skip_clear`` flags rows where the proposed
    value is empty but the current value is set — the apply handler must
    not overwrite a curated value with nothing, and the diff UI mutes the
    row so the user can see why no write will happen.
    """

    field: str
    current: str
    proposed: str
    changed: bool
    skip_clear: bool = False


# Field order matches the diff panel UX spec (title, authors, isbn, ...).
_FIELDS: tuple[str, ...] = (
    "title",
    "authors",
    "isbn",
    "language",
    "publisher",
    "series",
    "series_index",
    "description",
)


def _format_authors(authors: list[str]) -> str:
    """Join an author list for display; empty list renders as empty string."""
    return "; ".join(authors)


def _format_scalar(value: object) -> str:
    """Render an optional scalar value for display ("" when None)."""
    if value is None:
        return ""
    return str(value)


def _scalar_changed(current: object, proposed: object) -> bool:
    """True when ``current`` and ``proposed`` differ, treating None == ''."""
    cur = "" if current is None else str(current)
    prop = "" if proposed is None else str(proposed)
    return cur != prop


def _authors_changed(current: list[str], proposed: list[str]) -> bool:
    """True when ordered author lists differ."""
    return list(current) != list(proposed)


def metadata_diff(current: BookMetadata, proposed: BookMetadata) -> list[FieldDiff]:
    """Compute the per-field diff between two BookMetadata instances.

    Returns one :class:`FieldDiff` per displayable field in a fixed order so
    the diff panel always renders the same rows regardless of which sides
    are populated. ``None`` and empty string are treated as equivalent for
    every scalar field; authors are compared as ordered lists. Rows where
    the proposed value is empty and the current value is non-empty are
    flagged ``skip_clear`` so the apply pipeline can drop them.
    """
    diffs: list[FieldDiff] = []
    for field in _FIELDS:
        if field == "authors":
            cur_list = current.authors or []
            prop_list = proposed.authors or []
            changed = _authors_changed(cur_list, prop_list)
            skip_clear = changed and not prop_list and bool(cur_list)
            diffs.append(
                FieldDiff(
                    field=field,
                    current=_format_authors(cur_list),
                    proposed=_format_authors(prop_list),
                    changed=changed,
                    skip_clear=skip_clear,
                )
            )
            continue

        cur_val = getattr(current, field)
        prop_val = getattr(proposed, field)
        changed = _scalar_changed(cur_val, prop_val)
        cur_display = _format_scalar(cur_val)
        prop_display = _format_scalar(prop_val)
        skip_clear = changed and not prop_display and bool(cur_display)
        diffs.append(
            FieldDiff(
                field=field,
                current=cur_display,
                proposed=prop_display,
                changed=changed,
                skip_clear=skip_clear,
            )
        )
    return diffs

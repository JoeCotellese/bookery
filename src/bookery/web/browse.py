# ABOUTME: BrowseQuery + BrowsePage view models for the /books list controller.
# ABOUTME: Single source of truth for URL-driven browse state (q, page, sort, filters).

from collections.abc import Mapping
from dataclasses import dataclass, field

DEFAULT_PAGE_SIZE = 50

# Allowed sort keys for the /books list controller. Anything else falls back
# to ``DEFAULT_SORT`` silently — we never 400 the front door on a malformed
# query string. Bumping or renaming a key here is a behavior change and needs
# the template's header links updated in lock-step.
ALLOWED_SORTS: frozenset[str] = frozenset({"title", "author", "added"})
ALLOWED_DIRS: frozenset[str] = frozenset({"asc", "desc"})
# Default ordering matches the pre-sortable behavior of the list controller —
# books sorted by ``author_sort`` then ``title``, ascending — so unbookmarked
# users see no change after sortable columns land.
DEFAULT_SORT = "author"
DEFAULT_DIR = "asc"

# Allowed filter keys for the /books list controller. Anything else falls off
# silently — bookmarks and stale links shouldn't be able to either crash the
# query or smuggle unexpected SQL columns through. Bumping this set is a
# behavior change and needs the chip template's label map updated in lock-step.
ALLOWED_FILTERS: frozenset[str] = frozenset({"enriched", "format", "language", "status"})

# Value whitelists. ``enriched`` is a strict 0/1 toggle so any other value is
# nonsense. ``format`` and ``language`` are open-ended (any extension or BCP-47
# tag), but we lowercase and trim so the URL form is normalized for chip
# rendering and parameter binding.
_ENRICHED_VALUES: frozenset[str] = frozenset({"0", "1"})

# ``status`` filter maps to the read-status filter on /books. The UI carries
# an "All" affordance that maps to "no filter" — we drop ``all`` here so the
# chip strip and URL stay clean when nothing is filtered. Unknown values
# (case-mismatched, integer, garbage) fall off silently same as everything
# else in this layer.
_STATUS_VALUES: frozenset[str] = frozenset({"unread", "reading", "finished"})


@dataclass(frozen=True)
class BrowseQuery:
    """Parsed URL state for the /books list controller.

    ``sort``, ``dir``, and ``filters`` are validated at parse time so the
    controller and the catalog can trust them without re-checking. ``filters``
    is a mapping of whitelisted filter keys (see ``ALLOWED_FILTERS``) to
    their normalized values.
    """

    q: str = ""
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    sort: str = DEFAULT_SORT
    dir: str = DEFAULT_DIR
    filters: Mapping[str, str] = field(default_factory=dict)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    def with_page(self, page: int) -> "BrowseQuery":
        return BrowseQuery(
            q=self.q,
            page=max(1, page),
            page_size=self.page_size,
            sort=self.sort,
            dir=self.dir,
            filters=self.filters,
        )

    def without_filter(self, key: str) -> "BrowseQuery":
        """Return a copy with ``key`` removed from filters and page reset to 1.

        Changing the active filter set invalidates the page index (same
        convention as a sort change), so callers don't have to remember to
        reset the page when wiring chip dismiss links.
        """
        new_filters = {k: v for k, v in self.filters.items() if k != key}
        return BrowseQuery(
            q=self.q,
            page=1,
            page_size=self.page_size,
            sort=self.sort,
            dir=self.dir,
            filters=new_filters,
        )


def _coerce_int(value: str | None, default: int, minimum: int) -> int:
    """Parse ``value`` as an int >= ``minimum``; return ``default`` on garbage."""
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def _coerce_sort(value: str | None) -> str:
    """Return ``value`` if it's an allowed sort key; otherwise ``DEFAULT_SORT``.

    Unknown values (including the empty string, mis-cased variants, and
    obvious injection attempts) fall back silently — the list page is the
    front door and a stale URL shouldn't 400.
    """
    if value in ALLOWED_SORTS:
        return value
    return DEFAULT_SORT


def _coerce_dir(value: str | None) -> str:
    """Return ``value`` if it's an allowed direction; otherwise ``DEFAULT_DIR``."""
    if value in ALLOWED_DIRS:
        return value
    return DEFAULT_DIR


def _coerce_filters(args: Mapping[str, str]) -> dict[str, str]:
    """Pick out the known filter keys from ``args`` and normalize their values.

    Unknown keys are dropped silently (stale URLs shouldn't 400 the front
    door). Empty / whitespace-only values are also dropped — they encode
    "no filter" and shouldn't show up as a chip. ``enriched`` is whitelisted
    to ``{"0","1"}``; ``format`` and ``language`` are lowercased + trimmed so
    the URL form normalizes for chip rendering and SQL binding.
    """
    out: dict[str, str] = {}
    for key in ALLOWED_FILTERS:
        raw = args.get(key)
        if raw is None:
            continue
        value = raw.strip()
        if not value:
            continue
        if key == "enriched":
            if value not in _ENRICHED_VALUES:
                continue
            out[key] = value
        elif key == "status":
            normalized = value.lower()
            # ``all`` is the UI "no filter" affordance — drop it so the chip
            # strip stays empty and URLs round-trip cleanly.
            if normalized == "all":
                continue
            if normalized not in _STATUS_VALUES:
                continue
            out[key] = normalized
        else:
            out[key] = value.lower()
    return out


def from_request_args(
    args: Mapping[str, str], *, default_page_size: int = DEFAULT_PAGE_SIZE
) -> BrowseQuery:
    """Build a ``BrowseQuery`` from a Flask ``request.args``-shaped mapping.

    Tolerates missing or malformed inputs by falling back to defaults.
    ``page`` is clamped to ``>= 1``; the upper bound (total pages) is the
    controller's responsibility once it has a result count. ``sort`` and
    ``dir`` are validated against the allow-lists so unknown values render
    the default ordering instead of crashing the catalog query. Filter
    keys not in ``ALLOWED_FILTERS`` (and values failing per-key validation)
    are dropped silently.
    """
    return BrowseQuery(
        q=(args.get("q") or "").strip(),
        page=_coerce_int(args.get("page"), default=1, minimum=1),
        page_size=default_page_size,
        sort=_coerce_sort(args.get("sort")),
        dir=_coerce_dir(args.get("dir")),
        filters=_coerce_filters(args),
    )


@dataclass(frozen=True)
class BrowsePage:
    """Result of paginating a browse against the catalog.

    Combines the page's records with the totals derived from a single
    catalog round-trip so the template doesn't have to recompute bounds.
    """

    books: list
    total: int
    page: int
    page_size: int
    query: BrowseQuery

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0 or self.total <= 0:
            return 1
        return (self.total + self.page_size - 1) // self.page_size

    @property
    def start(self) -> int:
        if self.total == 0:
            return 0
        return (self.page - 1) * self.page_size + 1

    @property
    def end(self) -> int:
        if self.total == 0:
            return 0
        return min(self.page * self.page_size, self.total)

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

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


@dataclass(frozen=True)
class BrowseQuery:
    """Parsed URL state for the /books list controller.

    ``filters`` is reserved for plan-01 step 4. ``sort`` and ``dir`` are
    validated at parse time so the controller and the catalog can trust them
    without re-checking.
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


def from_request_args(
    args: Mapping[str, str], *, default_page_size: int = DEFAULT_PAGE_SIZE
) -> BrowseQuery:
    """Build a ``BrowseQuery`` from a Flask ``request.args``-shaped mapping.

    Tolerates missing or malformed inputs by falling back to defaults.
    ``page`` is clamped to ``>= 1``; the upper bound (total pages) is the
    controller's responsibility once it has a result count. ``sort`` and
    ``dir`` are validated against the allow-lists so unknown values render
    the default ordering instead of crashing the catalog query.
    """
    return BrowseQuery(
        q=(args.get("q") or "").strip(),
        page=_coerce_int(args.get("page"), default=1, minimum=1),
        page_size=default_page_size,
        sort=_coerce_sort(args.get("sort")),
        dir=_coerce_dir(args.get("dir")),
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

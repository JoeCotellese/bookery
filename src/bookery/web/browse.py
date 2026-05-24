# ABOUTME: BrowseQuery + BrowsePage view models for the /books list controller.
# ABOUTME: Single source of truth for URL-driven browse state (q, page, sort, filters).

from collections.abc import Mapping
from dataclasses import dataclass, field

DEFAULT_PAGE_SIZE = 50


@dataclass(frozen=True)
class BrowseQuery:
    """Parsed URL state for the /books list controller.

    Fields not yet exercised by the controller (``sort``, ``dir``, ``filters``)
    are reserved for plan-01 steps 3 and 4. Keeping them on the dataclass now
    lets the route plumbing land once and the later steps add behavior in
    isolation.
    """

    q: str = ""
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    sort: str = ""
    dir: str = ""
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


def from_request_args(
    args: Mapping[str, str], *, default_page_size: int = DEFAULT_PAGE_SIZE
) -> BrowseQuery:
    """Build a ``BrowseQuery`` from a Flask ``request.args``-shaped mapping.

    Tolerates missing or malformed inputs by falling back to defaults.
    ``page`` is clamped to ``>= 1``; the upper bound (total pages) is the
    controller's responsibility once it has a result count.
    """
    return BrowseQuery(
        q=(args.get("q") or "").strip(),
        page=_coerce_int(args.get("page"), default=1, minimum=1),
        page_size=default_page_size,
        sort=(args.get("sort") or "").strip(),
        dir=(args.get("dir") or "").strip(),
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

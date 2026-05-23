# [plan-01] Web List Browse Surface — paginated, sortable, filterable, responsive, semantic

## Defect

`/books` renders the full catalog as a single flat 6-column table. It has no pagination, no sort, no filter, no result count, no cover thumbnails, no responsive fallback, and inverts heading semantics (H1 = site name, H2 = page subject). The list is the front door of the app and currently fails at scanning, filtering, mobile, and accessibility simultaneously. Each gap is a symptom of the same defect: the list controller was never built around URL-driven browse state.

## Children

- #128 — paginate book list (renders all 600+ rows today)
- #136 — sortable columns (title/author/added)
- #137 — filter chips (enriched, format, language)
- #138 — result count display (Showing X–Y of Z)
- #139 — cover thumbnails on list and detail
- #129 — mobile card layout below 768px
- #126 — heading hierarchy: book/page title is H1, site name is a logo

## Fix sequence

1. **List controller takes a parsed `BrowseQuery`** (`q`, `page`, `sort`, `dir`, filter dict). Single source of truth for URL state. All list rendering goes through it.
2. **Server-side pagination** (50/page default). Search/sort/filter preserve `page` or reset to 1 deliberately. `Showing X–Y of Z` label derived from same query.
3. **Sortable column headers** push `?sort=...&dir=...` to the same controller. Chevron from active state.
4. **Filter chip strip** maps to the same query. URL-driven, dismissible, empty-state copy + clear-filters action.
5. **Cover extraction during import** (or lazy on first request) → `/books/<id>/cover` route → list thumb (40×60, `loading="lazy"`) + detail hero (160×240). Placeholder when missing.
6. **Responsive card layout** below 768px via CSS — same data, different shell. Whole card is the row link.
7. **Heading semantics pass**: site name becomes `<a class="logo">` (no heading role). `/books` H1 = "Library". Detail H1 = book title. Edit H1 = "Edit: <title>". Section headings drop to H2. axe-core clean.

## Test matrix

| Axis A (viewport) | Axis B (query) | Required behavior |
|---|---|---|
| 1280px | no filter | table layout, full columns, paginated, count rendered |
| 1280px | sort=author dir=desc | first row matches expected, chevron on header |
| 1280px | enriched=0&format=epub | only matching rows; dismiss chip → returns to base |
| 390px | no filter | stacked cards, no horizontal scroll, card is link |
| any | page=N out of range | last valid page rendered, no 500 |
| any | empty result | empty-state copy with clear-filters button |
| any | every route | exactly one H1, no heading-level skips (axe) |

The matrix lives in `tests/web/test_list_browse.py` and runs in CI.

## Out of scope

- Cover-image *quality* upgrades (resizing, dominant-color extraction) — fold in only if simple.
- Filter persistence across tabs/sessions — URL state is enough.
- Apply-candidate visual polish (plan-03).
- Edit form grouping / provenance panel (plan-04).
- Back-navigation / URL-on-htmx-swap state (plan-02).

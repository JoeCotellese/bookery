# [plan-02] Web Navigation & URL State — back, refresh, share, and form fallback all work

## Defect

htmx swaps were wired without a URL contract. Clicking Edit on detail does not change the URL, so refresh and direct nav lose state; the search input is not in a `<form>` so submitting via Enter / no-JS / AT does nothing; back navigation from detail / edit / diff lands on the unfiltered book list instead of the prior view; and once the user leaves detail for edit / enrich / diff the book title disappears entirely. Each gap is the same defect: the web layer assumes the htmx swap is the navigation, not the URL.

## Children

- #131 — edit URL handling: direct nav / refresh loses edit state
- #122 — back navigation returns to previous view, not book list
- #127 — persistent book context subhead on edit / enrich / diff
- #130 — search needs `<form>` fallback for no-JS / AT users

## Fix sequence

1. **Edit becomes a real URL.** `GET /books/<id>/edit` returns the full styled page on plain GET (`HX-Request` not set), and a fragment on htmx. `hx-push-url` on the swap so refresh and share work.
2. **Search wraps in `<form action="/books" method="get">`** with a real submit. htmx keystroke-search becomes progressive enhancement on top; submit and Enter still return filtered HTML server-side.
3. **Return-to mechanism.** Carry the originating list URL through detail / edit / diff via `?return_to=` query param (preferred over `Referer` — survives tab dupe and refresh). Detail/edit/diff back links use it. Deep-link with no `return_to` falls back to `/books`.
4. **Persistent book context subhead.** Layout helper renders `<a href="/books/<id>"><BookTitle> — <Author></a>` between site header and form/diff on all sub-flows. Survives htmx swaps.

## Test matrix

| Axis A (entry) | Axis B (action) | Required behavior |
|---|---|---|
| `/books?q=king` → detail | back | returns to `/books?q=king`, scroll preserved (best-effort) |
| `/books?page=3` → detail → edit | back | edit → detail; detail → `/books?page=3` |
| `/books/42/edit` direct GET | render | full styled page, edit form populated |
| `/books/42/edit` via htmx | render | fragment only, no base layout |
| refresh on `/books/42/edit` | render | full styled page, no state loss |
| no-JS user submits search | result | server returns `/books?q=...` filtered HTML |
| keyboard-only user, Enter on search | result | same as above; htmx not required |
| edit / enrich / diff page | render | persistent subhead with title + author + back link |

The matrix lives in `tests/web/test_navigation_state.py` and runs in CI.

## Out of scope

- Pagination/sort/filter URL contract (plan-01 owns the list controller).
- Per-field accept/reject on apply-candidate (plan-03).
- Apply diff visual highlighting and loading indicator (plan-03).
- Detail field grouping / hide-empty / provenance panel (plan-04).

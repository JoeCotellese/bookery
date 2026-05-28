# ABOUTME: Flask blueprint with route handlers for the Bookery web UI.
# ABOUTME: Handles book listing, detail view, search, and inline editing with htmx support.

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from bookery.core.config import get_library_root
from bookery.core.coverfetch import fetch_cover_image
from bookery.core.enrichment import dispatch_from_form, multi_provider_search
from bookery.core.pipeline import apply_metadata_safely
from bookery.core.remove import remove_book
from bookery.db.status import STATUS_FINISHED, STATUS_READING, STATUS_UNREAD
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.provider import MetadataProvider
from bookery.util.text import strip_html
from bookery.web.browse import BrowsePage, from_request_args
from bookery.web.candidate_payload import deserialize_candidate, serialize_candidate
from bookery.web.covers import get_or_extract_cover, invalidate_cover
from bookery.web.diff import metadata_diff

logger = logging.getLogger(__name__)

_STATUS_FROM_FORM: dict[str, int] = {
    "unread": STATUS_UNREAD,
    "reading": STATUS_READING,
    "finished": STATUS_FINISHED,
}


def _parse_status(value: str | None) -> int | None:
    """Translate a form ``status`` value into the integer constant.

    Returns ``None`` for missing or unknown values — the route then 400s
    so a bad form post fails loudly rather than silently rewriting the
    book to ``UNREAD``. Case-folded so a future client that posts the
    canonical title-case label still resolves.
    """
    if value is None:
        return None
    return _STATUS_FROM_FORM.get(value.strip().lower())


def _now_iso() -> str:
    """UTC ISO timestamp with seconds precision — matches the CLI status path."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _safe_return_to(value: str | None) -> str | None:
    """Sanitize a ``return_to`` query param to an internal path.

    The list controller stamps each row anchor with the originating list
    URL so detail / edit / diff back-links can return the user to the
    exact view they came from (filters, page, sort all intact). Because
    the value is user-controllable, we accept only absolute internal
    paths — anything with a scheme (``https://``), an authority
    (``//evil.com``), or a non-``/``-leading path falls back to ``None``
    so the consumer renders the default ``/books`` back-link. This
    prevents the param from being used as an open-redirect or a
    ``javascript:`` URL smuggle.
    """
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return None
    if not parsed.path.startswith("/"):
        return None
    return value


def _current_list_url() -> str:
    """Return the current request's path+query, suitable for ``return_to``.

    Flask's ``request.full_path`` always appends ``?`` even when the query
    string is empty, so we trim a lone trailing ``?`` to keep the value
    tidy for round-tripping through ``url_for``.
    """
    full = request.full_path
    if full.endswith("?"):
        return full[:-1]
    return full


def _file_context(book) -> dict[str, str]:
    """Best-effort file format + size for a BookRecord.

    Stat the output_path when present, otherwise the source_path. On any
    failure (missing file, permission error) the size renders as an em-dash.
    The format is derived from the path extension and uppercased.
    """
    path: Path | None = book.output_path or book.source_path
    fmt = ""
    size_display = "—"
    if path is not None:
        suffix = path.suffix.lstrip(".").upper()
        if suffix:
            fmt = suffix
        try:
            size_bytes = os.stat(path).st_size
            size_display = _format_size(size_bytes)
        except OSError:
            size_display = "—"
    return {"format": fmt, "size": size_display}


def _format_size(num_bytes: int) -> str:
    """Render a byte count as a short human-friendly string (e.g. '1.2 MB')."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


bp = Blueprint(
    "web",
    __name__,
    template_folder="templates",
    static_folder="static",
)


@bp.route("/")
def index():
    """Redirect root to book list."""
    return redirect(url_for("web.books"))


@bp.route("/books")
def books():
    """List books with URL-driven browse state (q, page).

    Single source of truth is a parsed ``BrowseQuery``. Pagination is
    server-side: ``catalog.browse`` returns the rows for the requested
    page plus the total match count so the controller can clamp an
    out-of-range page and render ``Showing X-Y of Z`` without a second
    query. Both htmx and full-page responses go through the same
    ``BrowsePage`` so the count, rows, and pager stay in lock-step.
    """
    catalog = current_app.config["CATALOG"]
    query = from_request_args(request.args)

    books_page, total = catalog.browse(
        q=query.q,
        offset=query.offset,
        limit=query.page_size,
        sort=query.sort,
        dir=query.dir,
        **query.filters,
    )

    # Clamp out-of-range page requests to the last valid page rather than
    # 404ing — bookmarks and stale links shouldn't break the front door.
    if total > 0 and not books_page and query.page > 1:
        last_page = max(1, (total + query.page_size - 1) // query.page_size)
        clamped = query.with_page(last_page)
        books_page, total = catalog.browse(
            q=clamped.q,
            offset=clamped.offset,
            limit=clamped.page_size,
            sort=clamped.sort,
            dir=clamped.dir,
            **clamped.filters,
        )
        query = clamped
    # ``query.filters`` already carries the ``status`` value when present, so
    # the kwargs splat above forwards it straight into ``catalog.browse``.
    # Nothing else to wire in this controller — the filter chip strip reads
    # from the same ``query.filters`` mapping.

    page = BrowsePage(
        books=books_page,
        total=total,
        page=query.page,
        page_size=query.page_size,
        query=query,
    )

    # One bulk status lookup for the visible page — every row's chip pulls
    # from this dict so the template stays cheap. Empty pages skip the call
    # entirely; the catalog method also short-circuits but the route is
    # considerate so the DB never sees the question.
    book_statuses = catalog.get_book_statuses([b.id for b in books_page]) if books_page else {}

    # ``list_url`` is what row anchors stamp into ``?return_to=`` so detail /
    # edit / diff back-links can return to this exact view (filters, page,
    # sort all preserved). Same value on both htmx and full-page paths.
    list_url = _current_list_url()
    if request.headers.get("HX-Request"):
        return render_template(
            "_book_list.html",
            page=page,
            query=query,
            list_url=list_url,
            book_statuses=book_statuses,
        )

    return render_template(
        "list.html",
        page=page,
        query=query,
        list_url=list_url,
        book_statuses=book_statuses,
    )


@bp.route("/books/<int:book_id>")
def book_detail(book_id):
    """Show detail page for a single book."""
    catalog = current_app.config["CATALOG"]
    book = catalog.get_by_id(book_id)
    if book is None:
        abort(404)

    tags = catalog.get_tags_for_book(book_id)
    genres = catalog.get_genres_for_book(book_id)
    file_info = _file_context(book)
    return_to = _safe_return_to(request.args.get("return_to"))
    book_status = catalog.get_book_status(book_id)
    device_read_state = catalog.get_device_read_state_for_book(book_id)
    queued_for_push = catalog.is_status_queued_for_push(book_id)

    if request.headers.get("HX-Request"):
        return render_template(
            "_detail.html",
            book=book,
            tags=tags,
            genres=genres,
            file_info=file_info,
            return_to=return_to,
            book_status=book_status,
            device_read_state=device_read_state,
            queued_for_push=queued_for_push,
        )

    return render_template(
        "detail.html",
        book=book,
        tags=tags,
        genres=genres,
        file_info=file_info,
        return_to=return_to,
        book_status=book_status,
        device_read_state=device_read_state,
        queued_for_push=queued_for_push,
    )


@bp.route("/books/bulk-status", methods=["POST"])
def bulk_update_status():
    """Apply one status to many books in a single transactional write.

    Form fields:
      - ``ids`` — repeated; each value must be an integer book id.
      - ``status`` — one of ``unread|reading|finished``.

    Returns the refreshed ``_book_list.html`` partial so an htmx swap on
    ``#book-list`` redraws the affected rows. Filter / sort context is
    reconstructed from the request URL so a bulk-mark on a filtered view
    doesn't fall back to "all books, default sort".
    """
    catalog = current_app.config["CATALOG"]

    raw_ids = request.form.getlist("ids")
    if not raw_ids:
        abort(400)
    try:
        ids = [int(value) for value in raw_ids]
    except (TypeError, ValueError):
        abort(400)

    status_int = _parse_status(request.form.get("status"))
    if status_int is None:
        abort(400)

    catalog.set_book_statuses_bulk(
        book_ids=ids,
        status=status_int,
        updated_at=_now_iso(),
    )

    # Re-render the list partial so the htmx response carries the updated
    # rows. Use the same browse query the user was looking at — filter and
    # pagination context come from the request URL.
    query = from_request_args(request.args)
    books_page, total = catalog.browse(
        q=query.q,
        offset=query.offset,
        limit=query.page_size,
        sort=query.sort,
        dir=query.dir,
        **query.filters,
    )
    page = BrowsePage(
        books=books_page,
        total=total,
        page=query.page,
        page_size=query.page_size,
        query=query,
    )
    book_statuses = (
        catalog.get_book_statuses([b.id for b in books_page]) if books_page else {}
    )
    list_url = _current_list_url()
    return render_template(
        "_book_list.html",
        page=page,
        query=query,
        list_url=list_url,
        book_statuses=book_statuses,
    )


@bp.route("/books/<int:book_id>/status", methods=["POST"])
def update_book_status(book_id):
    """Set the catalog read-status for a single book.

    Form field ``status`` is one of ``unread|reading|finished``. Unknown
    values 400 so a malformed form post never silently rewrites the row.
    Returns the ``_detail_reading.html`` partial so an htmx outer-swap on
    ``#detail-reading`` updates the section in place; the next
    ``bookery sync kobo`` is responsible for the device push.
    """
    catalog = current_app.config["CATALOG"]
    book = catalog.get_by_id(book_id)
    if book is None:
        abort(404)

    status_int = _parse_status(request.form.get("status"))
    if status_int is None:
        abort(400)

    catalog.set_book_status(book_id=book_id, status=status_int, updated_at=_now_iso())

    book_status = catalog.get_book_status(book_id)
    device_read_state = catalog.get_device_read_state_for_book(book_id)
    queued_for_push = catalog.is_status_queued_for_push(book_id)
    return render_template(
        "_detail_reading.html",
        book=book,
        book_status=book_status,
        device_read_state=device_read_state,
        queued_for_push=queued_for_push,
    )


@bp.route("/books/<int:book_id>/cover")
def book_cover(book_id):
    """Serve a book's cover image (lazy-extracted, on-disk cached).

    Resolves the cover from the library copy (``output_path``) if present,
    otherwise the source file. Missing books 404; books with no extractable
    cover get the inline SVG placeholder (200) so the ``<img>`` tag in the
    list/detail templates never falls back to a broken-image glyph. Successful
    extractions are cached under ``<library_root>/.covers/<book_id>.<ext>``;
    every response — placeholder included — sets a long ``Cache-Control`` so
    the browser handles the repeat case.
    """
    catalog = current_app.config["CATALOG"]
    book = catalog.get_by_id(book_id)
    if book is None:
        abort(404)

    epub_path: Path | None = book.output_path or book.source_path
    library_root = get_library_root()

    data, content_type = get_or_extract_cover(
        book_id=book_id,
        epub_path=epub_path,
        library_root=library_root,
    )

    response = make_response(data)
    response.headers["Content-Type"] = content_type
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@bp.route("/books/<int:book_id>/edit", methods=["GET"])
def edit_form(book_id):
    """Render the edit form for a book.

    htmx GET (``HX-Request`` header set) returns the bare partial for an
    in-place swap into ``#book-content``. A plain GET — direct nav, browser
    refresh, shared link — returns the full styled page so the user lands
    on a real URL rather than an unstyled fragment.
    """
    catalog = current_app.config["CATALOG"]
    book = catalog.get_by_id(book_id)
    if book is None:
        abort(404)

    file_info = _file_context(book)
    return_to = _safe_return_to(request.args.get("return_to"))
    if request.headers.get("HX-Request"):
        return render_template(
            "_edit_form.html", book=book, file_info=file_info, return_to=return_to
        )
    return render_template("edit.html", book=book, file_info=file_info, return_to=return_to)


@bp.route("/books/<int:book_id>/edit", methods=["POST"])
def update_book(book_id):
    """Save edited metadata and return the detail partial."""
    catalog = current_app.config["CATALOG"]
    book = catalog.get_by_id(book_id)
    if book is None:
        abort(404)

    title = request.form.get("title", "").strip()
    if not title:
        return (
            render_template(
                "_edit_form.html",
                book=book,
                file_info=_file_context(book),
                error="Title is required",
            ),
            400,
        )

    # Parse semicolon-separated authors
    authors_raw = request.form.get("authors", "").strip()
    authors = [a.strip() for a in authors_raw.split(";") if a.strip()] if authors_raw else []

    # Parse optional fields — empty string becomes None
    isbn = request.form.get("isbn", "").strip() or None
    language = request.form.get("language", "").strip() or None
    publisher = request.form.get("publisher", "").strip() or None
    # Strip HTML on write so storage is always plain text — the catalog is
    # the source of truth for the render layer and we never want to round-trip
    # markup through the FTS index or the edit textarea.
    description_raw = request.form.get("description", "")
    description = strip_html(description_raw) or None
    series = request.form.get("series", "").strip() or None

    series_index_raw = request.form.get("series_index", "").strip()
    series_index = float(series_index_raw) if series_index_raw else None

    catalog.update_book(
        book_id,
        title=title,
        authors=authors,
        isbn=isbn,
        language=language,
        publisher=publisher,
        description=description,
        series=series,
        series_index=series_index,
    )

    # Re-fetch updated book for display
    book = catalog.get_by_id(book_id)
    tags = catalog.get_tags_for_book(book_id)
    genres = catalog.get_genres_for_book(book_id)
    file_info = _file_context(book)

    return_to = _safe_return_to(request.args.get("return_to"))
    response = make_response(
        render_template(
            "_detail.html",
            book=book,
            tags=tags,
            genres=genres,
            file_info=file_info,
            return_to=return_to,
        )
    )
    # If the user came from the edit URL (/books/<id>/edit), push the URL
    # back to /books/<id> so refresh/share lands on detail, not on a stale
    # edit URL that would re-render the form. ``return_to`` rides along so
    # the breadcrumb on the now-pushed detail URL still resolves to the
    # originating list view.
    response.headers["HX-Push-Url"] = url_for(
        "web.book_detail", book_id=book_id, return_to=return_to or None
    )
    return response


def _prefill_for_book(book) -> tuple[str | None, str | None, str | None]:
    """Compute the search-form pre-fill values for a BookRecord.

    Returns ``(isbn, title, author)``. Title and author come from the
    book's structured metadata so providers receive them as separate
    arguments — concatenating them into a single free-text query produces
    misses on most provider search APIs.
    """
    isbn = book.metadata.isbn or None
    title = (book.metadata.title or "").strip() or None
    author = None
    if book.metadata.authors:
        first = (book.metadata.authors[0] or "").strip()
        author = first or None
    return isbn, title, author


@bp.route("/books/<int:book_id>/enrich", methods=["GET"])
def enrich_form(book_id):
    """Render the multi-provider search form for a book.

    htmx GET (``HX-Request`` header set) returns the bare partial for an
    in-place swap into ``#book-content``. A plain GET — direct nav, browser
    refresh, shared link — returns the full styled page so the user lands
    on a real URL rather than an unstyled fragment.

    Accepts optional ``isbn``/``title``/``author`` query params. When any
    are present, the form is prefilled with those values (overriding the
    metadata-based prefill) and the same multi-provider search is re-run
    so the candidate list is restored on the page. This is what the diff
    panel's "Back to results" button relies on to avoid forcing the user
    to retype their query.
    """
    catalog = current_app.config["CATALOG"]
    book = catalog.get_by_id(book_id)
    if book is None:
        abort(404)

    return_to = _safe_return_to(request.args.get("return_to"))

    query_isbn = (request.args.get("isbn") or "").strip()
    query_title = (request.args.get("title") or "").strip()
    query_author = (request.args.get("author") or "").strip()
    has_query = bool(query_isbn or query_title or query_author)

    if has_query:
        prefill_isbn = query_isbn or None
        prefill_title = query_title or None
        prefill_author = query_author or None
        providers = current_app.config.get("PROVIDERS", {})
        dispatch = dispatch_from_form(query_isbn, query_title, query_author)
        results = multi_provider_search(
            providers,
            isbn=dispatch.isbn,
            url=dispatch.url,
            title=dispatch.title,
            author=dispatch.author,
        )
        any_results = any(not r.is_empty for r in results)
    else:
        prefill_isbn, prefill_title, prefill_author = _prefill_for_book(book)
        results = None
        any_results = False

    template = "_enrich_search.html" if request.headers.get("HX-Request") else "enrich.html"
    return render_template(
        template,
        book=book,
        prefill_isbn=prefill_isbn,
        prefill_title=prefill_title,
        prefill_author=prefill_author,
        return_to=return_to,
        results=results,
        any_results=any_results,
    )


@bp.route("/books/<int:book_id>/enrich/search", methods=["POST"])
def enrich_search(book_id):
    """Run multi-provider candidate search and render grouped results."""
    catalog = current_app.config["CATALOG"]
    book = catalog.get_by_id(book_id)
    if book is None:
        abort(404)

    providers = current_app.config.get("PROVIDERS", {})

    dispatch = dispatch_from_form(
        request.form.get("isbn", ""),
        request.form.get("title", ""),
        request.form.get("author", ""),
    )

    results = multi_provider_search(
        providers,
        isbn=dispatch.isbn,
        url=dispatch.url,
        title=dispatch.title,
        author=dispatch.author,
    )
    any_results = any(not r.is_empty for r in results)

    # The View buttons rendered into the candidate list need to carry
    # enough state for the diff/apply routes to re-run the same provider
    # query and locate the chosen candidate by source_id. We pass the
    # populated dispatch slots as separate URL params rather than a single
    # merged "query" string — that's the bug that produced #209.
    return render_template(
        "_enrich_candidates.html",
        book=book,
        results=results,
        any_results=any_results,
        dispatch_isbn=dispatch.isbn or "",
        dispatch_url=dispatch.url or "",
        dispatch_title=dispatch.title or "",
        dispatch_author=dispatch.author or "",
    )


def _duplicate_cluster_count(catalog, output_path: Path | None, book_id: int) -> int:
    """Return the number of OTHER catalog rows sharing this output_path.

    Mirrors the duplicate-cluster query in ``core/remove.py`` so the
    confirm panel can surface the same warning the destructive action
    will eventually print.
    """
    if output_path is None:
        return 0
    cursor = catalog._conn.execute(
        "SELECT COUNT(*) FROM books WHERE output_path = ? AND id != ?",
        (str(output_path), book_id),
    )
    return int(cursor.fetchone()[0])


def _find_provider_by_name(name: str) -> MetadataProvider | None:
    """Look up a configured provider by its display name.

    ``providers`` is keyed by short id (``openlibrary``); the candidate
    rows carry the provider's human-facing ``name`` (``Open Library``).
    Iterate the registry so the route works with either key.
    """
    providers = current_app.config.get("PROVIDERS", {})
    for provider in providers.values():
        if provider.name == name:
            return provider
    return providers.get(name)


def _refetch_candidate(
    provider: MetadataProvider,
    *,
    isbn: str = "",
    url: str = "",
    title: str = "",
    author: str = "",
) -> list[MetadataCandidate]:
    """Re-run the original search against ``provider`` from dispatch slots.

    Diff/apply requests carry no candidate state across the wire, so we
    re-call the same dispatch path used by ``enrich_search`` and pick the
    candidate by ``source_id``. Only the populated slot is honored — the
    caller threads exactly one of ``isbn``/``url``/``title`` (with
    optional ``author``) back from the candidate row.
    """
    if isbn:
        return list(provider.search_by_isbn(isbn))
    if url:
        single = provider.lookup_by_url(url)
        return [single] if single is not None else []
    if title:
        return list(provider.search_by_title_author(title, author or None))
    return []


def _find_candidate(
    candidates: list[MetadataCandidate], candidate_id: str
) -> MetadataCandidate | None:
    """Locate a candidate by its provider-supplied ``source_id``."""
    for candidate in candidates:
        if candidate.source_id == candidate_id:
            return candidate
    return None


def _is_empty_scalar(value: object) -> bool:
    """True when a scalar metadata value is None or an empty/whitespace string."""
    if value is None:
        return True
    return isinstance(value, str) and value.strip() == ""


def _should_write_scalar(current: object, proposed: object) -> bool:
    """Decide whether to mirror ``proposed`` into the catalog row.

    Skip when the values are equivalent (no-op) or when proposed is empty
    while current is not — the apply pipeline must never silently wipe a
    curated value because the provider happened to lack one (issue #125).
    """
    if _is_empty_scalar(proposed) and not _is_empty_scalar(current):
        return False
    cur = "" if current is None else str(current)
    prop = "" if proposed is None else str(proposed)
    return cur != prop


def _should_write_authors(current: list[str], proposed: list[str]) -> bool:
    """Authors variant of :func:`_should_write_scalar` for the list field."""
    cur = current or []
    prop = proposed or []
    if not prop and cur:
        return False
    return list(cur) != list(prop)


@bp.route("/books/<int:book_id>/delete", methods=["GET"])
def delete_confirm(book_id):
    """Render the delete confirmation panel (htmx swap into #book-content)."""
    catalog = current_app.config["CATALOG"]
    book = catalog.get_by_id(book_id)
    if book is None:
        abort(404)

    tags = catalog.get_tags_for_book(book_id)
    genres = catalog.get_genres_for_book(book_id)
    file_info = _file_context(book)
    duplicate_count = _duplicate_cluster_count(catalog, book.output_path, book_id)

    return render_template(
        "_delete_confirm.html",
        book=book,
        file_info=file_info,
        tag_count=len(tags),
        genre_count=len(genres),
        duplicate_count=duplicate_count,
    )


@bp.route("/books/<int:book_id>/delete", methods=["POST"])
def delete_book(book_id):
    """Execute the remove and redirect (via HX-Redirect) to /books."""
    catalog = current_app.config["CATALOG"]
    if catalog.get_by_id(book_id) is None:
        abort(404)

    # Form field "keep_file" carries "1" or "0". Only the explicit "0"
    # opts in to deleting the file from disk; anything else (missing,
    # unexpected value, "1") preserves the file. We'd rather leak a file
    # than destroy one on a malformed request.
    keep_file = request.form.get("keep_file", "1") != "0"

    try:
        result = remove_book(catalog, book_id, keep_file=keep_file)
    except ValueError:
        # remove_book raises ValueError for unknown IDs; we already
        # checked above, so this is a race — surface as 404.
        abort(404)

    flash(f'Removed "{result.title}" by {result.author}', "success")
    for warning in result.warnings:
        flash(warning, "warning")

    # htmx clients honor HX-Redirect by navigating the browser; non-htmx
    # callers get a normal 303 redirect back to the list.
    response = make_response("", 200)
    response.headers["HX-Redirect"] = url_for("web.books")
    return response


def _hx_redirect(target_url: str) -> Response:
    """Empty 200 carrying an ``HX-Redirect`` so the htmx client navigates the browser.

    Several enrich-apply exits (success and the various recoverable failures)
    all need the same "do nothing in-place, send the browser to ``target_url``"
    shape; this keeps that response in one spot.
    """
    response = make_response("", 200)
    response.headers["HX-Redirect"] = target_url
    return response


@bp.route("/books/<int:book_id>/enrich/candidate", methods=["GET"])
def enrich_candidate(book_id):
    """Render the field-by-field diff panel for a chosen candidate.

    Re-fetches the candidate from its provider using the original query so
    no per-session state is required. The chosen candidate is serialized into
    the Apply form (issue #234) so Apply writes exactly what was previewed
    without re-querying the provider.

    htmx GET (``HX-Request`` header set) returns the bare partial for an
    in-place swap into ``#book-content``. A plain GET — direct nav, browser
    refresh, shared link — returns the full styled page so the user lands
    on a real URL rather than an unstyled fragment.

    If the provider is unreachable or the candidate has drifted out of its
    result set, render a recoverable inline message rather than a bare 404 so
    the user's other results remain reachable (issue #234).
    """
    catalog = current_app.config["CATALOG"]
    book = catalog.get_by_id(book_id)
    if book is None:
        abort(404)

    provider_name = request.args.get("provider", "")
    isbn = request.args.get("isbn", "")
    url = request.args.get("url", "")
    title = request.args.get("title", "")
    author = request.args.get("author", "")
    candidate_id = request.args.get("candidate_id", "")
    return_to = _safe_return_to(request.args.get("return_to"))

    provider = _find_provider_by_name(provider_name)
    candidate = None
    if provider is not None:
        candidates = _refetch_candidate(provider, isbn=isbn, url=url, title=title, author=author)
        candidate = _find_candidate(candidates, candidate_id)

    if candidate is None:
        return _render_enrich_candidate_error(
            book,
            provider_name=provider_name,
            isbn=isbn,
            url=url,
            title=title,
            author=author,
            candidate_id=candidate_id,
            return_to=return_to,
        )

    diffs = metadata_diff(book.metadata, candidate.metadata)

    template = (
        "_enrich_diff.html" if request.headers.get("HX-Request") else "enrich_candidate.html"
    )
    return render_template(
        template,
        book=book,
        candidate=candidate,
        diffs=diffs,
        provider_name=provider_name,
        dispatch_isbn=isbn,
        dispatch_url=url,
        dispatch_title=title,
        dispatch_author=author,
        candidate_id=candidate_id,
        candidate_payload=serialize_candidate(candidate),
        return_to=return_to,
    )


def _render_enrich_candidate_error(
    book,
    *,
    provider_name: str,
    isbn: str,
    url: str,
    title: str,
    author: str,
    candidate_id: str,
    return_to: str | None,
):
    """Render a recoverable "couldn't load this candidate" panel (issue #234).

    htmx requests get the bare fragment for an in-place swap; a plain GET gets
    the full styled page so direct nav/refresh lands on a real URL. Both offer
    Try again / Back to results so the selection is never a dead end.
    """
    context = {
        "book": book,
        "provider_name": provider_name,
        "dispatch_isbn": isbn,
        "dispatch_url": url,
        "dispatch_title": title,
        "dispatch_author": author,
        "candidate_id": candidate_id,
        "return_to": return_to,
    }
    if request.headers.get("HX-Request"):
        return render_template("_enrich_candidate_error.html", **context)
    return render_template("enrich_candidate.html", load_error=True, **context)


@bp.route("/books/<int:book_id>/enrich/apply", methods=["POST"])
def enrich_apply(book_id):
    """Apply the selected candidate's metadata to a non-destructive copy.

    Writes the proposed metadata to a new EPUB copy via
    ``apply_metadata_safely``, then mirrors the same fields into the
    catalog and records the output path. Emits a success flash and an
    ``HX-Redirect`` so the htmx client navigates back to the refreshed
    detail page.

    Missing source files short-circuit with an error flash and no catalog
    writes; write-pipeline failures (verification, IO) likewise leave the
    catalog untouched.
    """
    catalog = current_app.config["CATALOG"]
    book = catalog.get_by_id(book_id)
    if book is None:
        abort(404)

    detail_url = url_for("web.book_detail", book_id=book_id)

    provider_name = request.form.get("provider", "")
    isbn = request.form.get("isbn", "")
    url = request.form.get("url", "")
    title = request.form.get("title", "")
    author = request.form.get("author", "")
    candidate_id = request.form.get("candidate_id", "")

    # Prefer the candidate the user previewed, carried verbatim in the form, so
    # Apply writes exactly what the diff showed without a provider round-trip
    # (#234). A missing/malformed/tampered payload falls back to re-fetching by
    # dispatch slot — the original stateless path — so older clients still work.
    candidate = deserialize_candidate(request.form.get("candidate_payload", ""))
    if candidate is None:
        provider = _find_provider_by_name(provider_name)
        if provider is not None:
            candidates = _refetch_candidate(
                provider, isbn=isbn, url=url, title=title, author=author
            )
            candidate = _find_candidate(candidates, candidate_id)

    if candidate is None:
        # Neither the carried payload nor a re-fetch could recover the
        # selection. Don't 404 a confirmed Apply — flash and bounce back to the
        # detail page so the user can retry from a clean state (#234).
        flash(
            "Could not apply: the selected candidate is no longer available — search again.",
            "error",
        )
        return _hx_redirect(detail_url)

    # The library copy is the canonical file post-import. The original
    # source_path may no longer exist (e.g. user emptied Calibre's trash
    # after importing from there), so prefer output_path when it's readable.
    library_copy = book.output_path
    if library_copy is not None and library_copy.exists():
        source = library_copy
    else:
        source = book.source_path
    if source is None or not source.exists():
        flash(
            "Cannot apply: no readable EPUB for this book "
            f"(source={book.source_path}, library={book.output_path})",
            "error",
        )
        return _hx_redirect(detail_url)

    # Prefer the existing library location of this book (its previous output
    # copy's parent) so multiple enrich passes don't scatter files across
    # the filesystem. Fall back to the source file's directory.
    output_dir = book.output_path.parent if book.output_path is not None else source.parent

    proposed = candidate.metadata

    # Fetch the candidate's cover (if any) so it lands in the same atomic write
    # as the text fields. A cover fetch failure is non-fatal: the text metadata
    # still applies, and we note the skipped cover in the success flash.
    cover_image: bytes | None = None
    cover_skipped = False
    if proposed.cover_url:
        cover_image = fetch_cover_image(proposed.cover_url)
        if cover_image is None:
            cover_skipped = True
            logger.warning(
                "enrich_apply: cover fetch failed for book %s from %s",
                book_id,
                proposed.cover_url,
            )

    write_result = apply_metadata_safely(
        source, proposed, output_dir, cover_image=cover_image
    )
    if not write_result.success or write_result.path is None:
        flash(
            f"Apply failed: {write_result.error or 'unknown error'}",
            "error",
        )
        return _hx_redirect(detail_url)

    # Mirror the candidate's fields into the catalog with provenance credited
    # to the provider. We intentionally only write fields that the provider
    # supplied so untouched values (e.g. an unset ISBN) don't clobber what
    # the user already curated. Defense in depth for issue #125: never
    # overwrite a non-empty current value with an empty proposed value —
    # even if a form post somehow forces the clearing value through.
    current = book.metadata
    update_fields: dict[str, object] = {}
    if _should_write_scalar(current.title, proposed.title):
        update_fields["title"] = proposed.title
    if _should_write_authors(current.authors, proposed.authors):
        update_fields["authors"] = list(proposed.authors)
    if _should_write_scalar(current.isbn, proposed.isbn):
        update_fields["isbn"] = proposed.isbn
    if _should_write_scalar(current.language, proposed.language):
        update_fields["language"] = proposed.language
    if _should_write_scalar(current.publisher, proposed.publisher):
        update_fields["publisher"] = proposed.publisher
    # Provider descriptions are commonly HTML (Google Books, scraped OL).
    # Strip on write so the catalog stores plain text — mirrors the same
    # guarantee the edit form path enforces. Compare against the stripped
    # value too so an HTML-wrapped echo of the current text doesn't read as
    # a real change.
    stripped_description = strip_html(proposed.description) if proposed.description else None
    if _should_write_scalar(current.description, stripped_description):
        update_fields["description"] = stripped_description
    if _should_write_scalar(current.series, proposed.series):
        update_fields["series"] = proposed.series
    if _should_write_scalar(current.series_index, proposed.series_index):
        update_fields["series_index"] = proposed.series_index

    # Credit provenance to the candidate's source — the provider's canonical
    # name captured when the candidate was built at View time, carried in the
    # payload (or recovered via the fallback re-fetch).
    catalog.update_book(
        book_id,
        source=candidate.source,
        confidence=candidate.confidence,
        **update_fields,
    )
    catalog.set_output_path(book_id, write_result.path)
    catalog.set_matched_at(book_id)

    # The rewritten copy is a new file (collision-resolved name) and, when a
    # cover was embedded, different bytes. Drop the stale on-disk cover cache so
    # the next GET /books/<id>/cover re-extracts from the new file.
    invalidate_cover(get_library_root(), book_id)

    message = f'Applied "{proposed.title}" from {candidate.source}'
    if cover_skipped:
        message += " (cover could not be fetched and was skipped)"
    flash(message, "success")
    return _hx_redirect(detail_url)

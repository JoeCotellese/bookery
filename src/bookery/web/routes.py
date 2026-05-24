# ABOUTME: Flask blueprint with route handlers for the Bookery web UI.
# ABOUTME: Handles book listing, detail view, search, and inline editing with htmx support.

import os
from pathlib import Path

from flask import (
    Blueprint,
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
from bookery.core.enrichment import dispatch_from_form, multi_provider_search
from bookery.core.pipeline import apply_metadata_safely
from bookery.core.remove import remove_book
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.provider import MetadataProvider
from bookery.util.text import strip_html
from bookery.web.browse import BrowsePage, from_request_args
from bookery.web.covers import get_or_extract_cover
from bookery.web.diff import metadata_diff


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

    page = BrowsePage(
        books=books_page,
        total=total,
        page=query.page,
        page_size=query.page_size,
        query=query,
    )

    if request.headers.get("HX-Request"):
        return render_template("_book_list.html", page=page, query=query)

    return render_template("list.html", page=page, query=query)


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

    if request.headers.get("HX-Request"):
        return render_template(
            "_detail.html", book=book, tags=tags, genres=genres, file_info=file_info
        )

    return render_template("detail.html", book=book, tags=tags, genres=genres, file_info=file_info)


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
    if request.headers.get("HX-Request"):
        return render_template("_edit_form.html", book=book, file_info=file_info)
    return render_template("edit.html", book=book, file_info=file_info)


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

    response = make_response(
        render_template("_detail.html", book=book, tags=tags, genres=genres, file_info=file_info)
    )
    # If the user came from the edit URL (/books/<id>/edit), push the URL
    # back to /books/<id> so refresh/share lands on detail, not on a stale
    # edit URL that would re-render the form.
    response.headers["HX-Push-Url"] = url_for("web.book_detail", book_id=book_id)
    return response


def _prefill_for_book(book) -> tuple[str | None, str | None]:
    """Compute the search-form pre-fill values for a BookRecord.

    Returns ``(isbn, free_text_query)``. ISBN is preferred when present;
    otherwise a ``"title author"`` string is composed for the free-text input.
    Either tuple slot may be ``None``.
    """
    isbn = book.metadata.isbn or None
    if isbn:
        return isbn, None
    parts = [book.metadata.title or ""]
    if book.metadata.authors:
        parts.append(book.metadata.authors[0])
    query = " ".join(p for p in parts if p).strip()
    return None, query or None


@bp.route("/books/<int:book_id>/enrich", methods=["GET"])
def enrich_form(book_id):
    """Render the multi-provider search form for a book."""
    catalog = current_app.config["CATALOG"]
    book = catalog.get_by_id(book_id)
    if book is None:
        abort(404)

    prefill_isbn, prefill_query = _prefill_for_book(book)
    return render_template(
        "_enrich_search.html",
        book=book,
        prefill_isbn=prefill_isbn,
        prefill_query=prefill_query,
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
        request.form.get("query", ""),
    )

    results = multi_provider_search(
        providers,
        isbn=dispatch.isbn,
        url=dispatch.url,
        title_author=dispatch.title_author,
    )
    any_results = any(not r.is_empty for r in results)

    # Reconstruct the query string passed to the diff route so View can
    # re-fetch without keeping per-session state. Whatever dispatch path
    # was taken (ISBN, URL, title/author), the diff route's own
    # ``dispatch_from_form`` will resolve the same shape.
    diff_query = dispatch.isbn or dispatch.url or dispatch.title_author or ""

    return render_template(
        "_enrich_candidates.html",
        book=book,
        results=results,
        any_results=any_results,
        diff_query=diff_query,
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


def _refetch_candidate(provider: MetadataProvider, query: str) -> list[MetadataCandidate]:
    """Re-run the original search against ``provider`` for ``query``.

    Apply requests carry no candidate state across the wire, so we re-call
    the same dispatch path used by ``enrich_search`` and pick the candidate
    by ``source_id``. ISBN-shaped queries hit ``search_by_isbn``, URLs go to
    ``lookup_by_url``, everything else is treated as a title/author search.
    """
    dispatch = dispatch_from_form("", query)
    if dispatch.isbn:
        return list(provider.search_by_isbn(dispatch.isbn))
    if dispatch.url:
        single = provider.lookup_by_url(dispatch.url)
        return [single] if single is not None else []
    if dispatch.title_author:
        return list(provider.search_by_title_author(dispatch.title_author))
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


@bp.route("/books/<int:book_id>/enrich/candidate", methods=["GET"])
def enrich_candidate(book_id):
    """Render the field-by-field diff panel for a chosen candidate.

    Re-fetches the candidate from its provider using the original query so
    no per-session state is required. The diff panel includes an Apply form
    that POSTs back to ``enrich_apply`` with the same dispatch params.
    """
    catalog = current_app.config["CATALOG"]
    book = catalog.get_by_id(book_id)
    if book is None:
        abort(404)

    provider_name = request.args.get("provider", "")
    query = request.args.get("query", "")
    candidate_id = request.args.get("candidate_id", "")

    provider = _find_provider_by_name(provider_name)
    if provider is None:
        abort(404)

    candidates = _refetch_candidate(provider, query)
    candidate = _find_candidate(candidates, candidate_id)
    if candidate is None:
        abort(404)

    diffs = metadata_diff(book.metadata, candidate.metadata)

    return render_template(
        "_enrich_diff.html",
        book=book,
        candidate=candidate,
        diffs=diffs,
        provider_name=provider_name,
        query=query,
        candidate_id=candidate_id,
    )


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

    provider_name = request.form.get("provider", "")
    query = request.form.get("query", "")
    candidate_id = request.form.get("candidate_id", "")

    provider = _find_provider_by_name(provider_name)
    if provider is None:
        abort(404)

    candidates = _refetch_candidate(provider, query)
    candidate = _find_candidate(candidates, candidate_id)
    if candidate is None:
        abort(404)

    detail_url = url_for("web.book_detail", book_id=book_id)

    source = book.source_path
    if source is None or not source.exists():
        flash(
            f"Cannot apply: source file is missing ({source})",
            "error",
        )
        response = make_response("", 200)
        response.headers["HX-Redirect"] = detail_url
        return response

    # Prefer the existing library location of this book (its previous output
    # copy's parent) so multiple enrich passes don't scatter files across
    # the filesystem. Fall back to the source file's directory.
    output_dir = book.output_path.parent if book.output_path is not None else source.parent

    proposed = candidate.metadata
    write_result = apply_metadata_safely(source, proposed, output_dir)
    if not write_result.success or write_result.path is None:
        flash(
            f"Apply failed: {write_result.error or 'unknown error'}",
            "error",
        )
        response = make_response("", 200)
        response.headers["HX-Redirect"] = detail_url
        return response

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

    # Always credit provenance to the matched provider's canonical name
    # rather than echoing the user-supplied form value verbatim.
    catalog.update_book(
        book_id,
        source=provider.name,
        confidence=candidate.confidence,
        **update_fields,
    )
    catalog.set_output_path(book_id, write_result.path)
    catalog.set_matched_at(book_id)

    flash(
        f'Applied "{proposed.title}" from {provider.name}',
        "success",
    )
    response = make_response("", 200)
    response.headers["HX-Redirect"] = detail_url
    return response

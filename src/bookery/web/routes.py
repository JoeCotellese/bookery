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

from bookery.core.enrichment import dispatch_from_form, multi_provider_search
from bookery.core.remove import remove_book


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
    """List all books, with optional search via query param."""
    catalog = current_app.config["CATALOG"]
    query = request.args.get("q", "").strip()

    book_list = catalog.search(query) if query else catalog.list_all_by_author()

    if request.headers.get("HX-Request"):
        return render_template("_table.html", books=book_list, query=query)

    return render_template("list.html", books=book_list, query=query)


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


@bp.route("/books/<int:book_id>/edit", methods=["GET"])
def edit_form(book_id):
    """Return the edit form partial for a book."""
    catalog = current_app.config["CATALOG"]
    book = catalog.get_by_id(book_id)
    if book is None:
        abort(404)

    file_info = _file_context(book)
    return render_template("_edit_form.html", book=book, file_info=file_info)


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
    description = request.form.get("description", "").strip() or None
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

    return render_template(
        "_detail.html", book=book, tags=tags, genres=genres, file_info=file_info
    )


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

    return render_template(
        "_enrich_candidates.html",
        results=results,
        any_results=any_results,
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

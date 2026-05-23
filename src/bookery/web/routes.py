# ABOUTME: Flask blueprint with route handlers for the Bookery web UI.
# ABOUTME: Handles book listing, detail view, search, and inline editing with htmx support.

import os
from pathlib import Path

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for


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

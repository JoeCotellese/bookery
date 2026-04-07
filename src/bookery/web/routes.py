# ABOUTME: Flask blueprint with route handlers for the Bookery web UI.
# ABOUTME: Handles book listing, detail view, and search with htmx support.

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for

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

    return render_template("detail.html", book=book, tags=tags, genres=genres)

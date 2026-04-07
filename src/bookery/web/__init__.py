# ABOUTME: Flask app factory for the Bookery web UI.
# ABOUTME: Creates the Flask application with catalog dependency injection.

from flask import Flask

from bookery.db.catalog import LibraryCatalog
from bookery.web.routes import bp


def create_app(catalog: LibraryCatalog) -> Flask:
    """Create and configure the Flask application.

    Args:
        catalog: LibraryCatalog instance for database access.
    """
    app = Flask(__name__)
    app.config["CATALOG"] = catalog
    app.register_blueprint(bp)
    return app

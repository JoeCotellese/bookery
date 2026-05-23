# ABOUTME: Flask app factory for the Bookery web UI.
# ABOUTME: Creates the Flask application with catalog dependency injection.

import os
from collections.abc import Mapping

from flask import Flask

from bookery.db.catalog import LibraryCatalog
from bookery.metadata.provider import MetadataProvider
from bookery.web.routes import bp


def create_app(
    catalog: LibraryCatalog,
    providers: Mapping[str, MetadataProvider] | None = None,
) -> Flask:
    """Create and configure the Flask application.

    Args:
        catalog: LibraryCatalog instance for database access.
        providers: Mapping of provider key → MetadataProvider used for the
            enrich search fan-out. Order is preserved when iterating. Defaults
            to an empty mapping, which renders enrich search with no provider
            groups (route still functions for tests that don't need providers).
    """
    app = Flask(__name__)
    # SECRET_KEY is required for Flask sessions (and therefore flashed
    # messages). We ship a dev default so the local CLI/test workflows
    # work out of the box, but operators should override via the
    # BOOKERY_SECRET_KEY environment variable in any shared deployment.
    app.config["SECRET_KEY"] = os.environ.get("BOOKERY_SECRET_KEY", "bookery-dev-secret")
    app.config["CATALOG"] = catalog
    app.config["PROVIDERS"] = dict(providers) if providers else {}
    app.register_blueprint(bp)
    return app

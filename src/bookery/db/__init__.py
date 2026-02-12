# ABOUTME: Public API for the Bookery library database layer.
# ABOUTME: Exports connection management, catalog operations, and data types.

from bookery.db.catalog import DuplicateBookError, LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library
from bookery.db.hashing import compute_file_hash
from bookery.db.mapping import BookRecord

__all__ = [
    "DEFAULT_DB_PATH",
    "BookRecord",
    "DuplicateBookError",
    "LibraryCatalog",
    "compute_file_hash",
    "open_library",
]

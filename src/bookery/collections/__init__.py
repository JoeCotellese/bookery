# ABOUTME: Pure collections query package — parses/validates rule-based collection queries.
# ABOUTME: Quarantines the luqum dependency; has no database import.

from bookery.collections.query import (
    SLICE3_FIELD_NAMES,
    CollectionQuery,
    CollectionQueryError,
    parse_collection_query,
)

__all__ = [
    "SLICE3_FIELD_NAMES",
    "CollectionQuery",
    "CollectionQueryError",
    "parse_collection_query",
]

# ABOUTME: Pure collections query package — parses/validates rule-based collection queries.
# ABOUTME: Quarantines the luqum dependency; has no database import.

from bookery.collections.lucene_compose import append_clause, quote_value
from bookery.collections.query import (
    QUERY_FIELD_NAMES,
    CollectionQueryError,
    Op,
    QueryAnd,
    QueryNode,
    QueryNot,
    QueryOr,
    QueryTerm,
    parse_collection_query,
)

__all__ = [
    "QUERY_FIELD_NAMES",
    "CollectionQueryError",
    "Op",
    "QueryAnd",
    "QueryNode",
    "QueryNot",
    "QueryOr",
    "QueryTerm",
    "append_clause",
    "parse_collection_query",
    "quote_value",
]

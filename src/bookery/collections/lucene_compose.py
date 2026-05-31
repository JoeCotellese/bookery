# ABOUTME: Pure Lucene clause composer for the collection query builder.
# ABOUTME: Produces engine-valid AND-appended clauses; no DB, no Flask import.

import re

# A "simple" value needs no quoting: word characters only, so it lexes as a bare
# Lucene Word with no significant characters. Everything else (spaces, colons,
# brackets, hyphens, quotes, ...) is emitted as a quoted phrase to stay valid.
_BARE_SAFE = re.compile(r"^[A-Za-z0-9_]+$")

# Lucene keywords that must be quoted even though they are word-only, since a bare
# emission would be parsed as an operator rather than a term value.
_RESERVED_WORDS = frozenset({"AND", "OR", "NOT", "TO"})


def quote_value(value: str) -> str:
    """Render a raw value as an engine-valid Lucene operand.

    Simple word-only values that are not Lucene keywords are returned bare
    (``Dune`` -> ``Dune``). Anything else becomes a double-quoted phrase with ``\\``
    and ``"`` escaped, which the parser accepts for every whitelisted field
    (``Frank Herbert`` -> ``"Frank Herbert"``).
    """
    if _BARE_SAFE.match(value) and value.upper() not in _RESERVED_WORDS:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def append_clause(existing: str, field: str, value: str, op: str = "AND") -> str:
    """Append a ``field:value`` clause to an existing raw query string.

    The first clause stands alone; subsequent clauses are joined with `` {op} ``
    (default ``AND``). The value is quoted via :func:`quote_value` so the result is
    always valid against ``parse_collection_query``. The builder never parses
    ``existing`` back — it is treated as opaque text the user may have hand-edited.
    """
    clause = f"{field}:{quote_value(value)}"
    existing = existing.strip()
    if not existing:
        return clause
    return f"{existing} {op} {clause}"

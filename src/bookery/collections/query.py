# ABOUTME: Parses and validates rule-based collection queries (slice-3 subset).
# ABOUTME: Pure module — owns the luqum dependency, no DB import; SQL lives in the resolver.

from collections.abc import Callable
from dataclasses import dataclass

from luqum.exceptions import ParseError
from luqum.parser import parser
from luqum.tree import Phrase, SearchField, Word

from bookery.metadata.genres import CANONICAL_GENRES, is_canonical_genre


class CollectionQueryError(ValueError):
    """A collection query string is invalid or outside the supported subset.

    Carries a human-facing message; the CLI and web layers surface it verbatim.
    Subclasses ``ValueError`` so existing ``except ValueError`` catch sites in the
    catalog keep working.
    """


@dataclass(frozen=True)
class CollectionQuery:
    """A validated single-field equality query.

    ``field`` is a canonical, lower-cased slice-3 field name (``series`` or
    ``genre``); ``value`` is the raw user-supplied value (quotes stripped). The
    resolver turns this into per-field SQL — this object holds no SQL itself.
    """

    field: str
    value: str


def _validate_genre_value(value: str) -> None:
    """Reject non-canonical genres at parse time (mirrors ``get_books_by_genre``)."""
    if not is_canonical_genre(value):
        valid = ", ".join(CANONICAL_GENRES)
        raise CollectionQueryError(
            f"'{value}' is not a canonical genre. Valid genres: {valid}."
        )


# The slice-3 field whitelist. Maps each supported field to an optional value
# validator. This registry drives both the compiler (in the db resolver, which
# keys off these names) and the error messages below. Slice 4 (#236) grows this
# map and relaxes the validator; the parse entry point does not change.
SLICE3_FIELDS: dict[str, Callable[[str], None] | None] = {
    "series": None,
    "genre": _validate_genre_value,
}
SLICE3_FIELD_NAMES: tuple[str, ...] = tuple(SLICE3_FIELDS)

# Fields deliberately deferred to a later slice, mapped to where they land. These
# get a specific "coming later" message rather than the generic unknown-field error.
_DEFERRED_FIELDS: dict[str, str] = {
    "author": "slice 4 (#236)",
}

_FIELD_LIST = ", ".join(SLICE3_FIELD_NAMES)
_SYNTAX_MSG = (
    f"Invalid query syntax. Use a single term like 'genre:\"Science Fiction\"' "
    f"or 'series:Dune' (valid fields: {_FIELD_LIST})."
)
_SINGLE_TERM_MSG = (
    f"Only a single field:value term is supported in this release "
    f"(e.g. 'genre:\"Science Fiction\"'). Valid fields: {_FIELD_LIST}."
)
_UNSUPPORTED_VALUE_MSG = (
    "Wildcards, ranges, and comparisons are not supported in this release — "
    "use an exact field:value, e.g. 'series:Dune'."
)


def parse_collection_query(raw: str) -> CollectionQuery:
    """Parse and validate a rule-based collection query.

    Parse-permissive, validate-restrictive: luqum parses the full Lucene grammar,
    then the AST is walked and anything outside the slice-3 subset is rejected. A
    valid query is exactly one ``field:value`` or ``field:"phrase"`` term over a
    whitelisted field.

    Raises:
        CollectionQueryError: on syntax errors, multi-term/boolean queries,
            unknown/deferred fields, unsupported value shapes (wildcards/ranges),
            or non-canonical genre values.
    """
    text = raw.strip()
    if not text:
        raise CollectionQueryError(_SYNTAX_MSG)

    try:
        tree = parser.parse(text)
    except ParseError as exc:
        raise CollectionQueryError(_SYNTAX_MSG) from exc

    # A single field:value term parses to a SearchField at the top level. Anything
    # else — implicit multi-term (UnknownOperation), explicit AND/OR (And/OrOperation),
    # NOT, a parenthesised Group, or a bare Word/Phrase with no field — is rejected.
    if not isinstance(tree, SearchField):
        raise CollectionQueryError(_SINGLE_TERM_MSG)

    expr = tree.expr
    if isinstance(expr, Phrase):
        value = _strip_quotes(expr.value)
    elif isinstance(expr, Word):
        value = expr.value
        if "*" in value or "?" in value:
            raise CollectionQueryError(_UNSUPPORTED_VALUE_MSG)
    else:
        # Range, Fuzzy, Proximity, etc. — not part of the slice-3 subset.
        raise CollectionQueryError(_UNSUPPORTED_VALUE_MSG)

    field = tree.name.lower()

    if field in _DEFERRED_FIELDS:
        raise CollectionQueryError(
            f"Field '{field}' is not yet supported — coming in {_DEFERRED_FIELDS[field]}."
        )
    if field not in SLICE3_FIELDS:
        raise CollectionQueryError(
            f"Unknown field '{tree.name}'. Valid fields: {_FIELD_LIST}."
        )

    validate_value = SLICE3_FIELDS[field]
    if validate_value is not None:
        validate_value(value)

    return CollectionQuery(field=field, value=value)


def _strip_quotes(phrase_value: str) -> str:
    """Strip the surrounding double quotes luqum keeps on a Phrase's value."""
    if len(phrase_value) >= 2 and phrase_value[0] == '"' and phrase_value[-1] == '"':
        return phrase_value[1:-1]
    return phrase_value

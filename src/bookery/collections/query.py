# ABOUTME: Parses and validates rule-based collection queries into a small query IR.
# ABOUTME: Pure module — owns the luqum dependency, no DB import; SQL lives in the resolver.

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

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


class Op(StrEnum):
    """How a leaf term matches its field.

    The parser resolves each leaf to exactly one ``Op`` from both the field's
    capabilities and the parsed value shape; the resolver keys its SQL off it.
    """

    EQ = "eq"  # exact, case-insensitive equality
    CONTAINS = "contains"  # substring match (free-text people/subject fields)
    PREFIX = "prefix"  # left-anchored prefix match (``title:dune*``)


@dataclass(frozen=True)
class QueryTerm:
    """A validated single-field leaf of the query IR.

    ``field`` is a canonical, lower-cased whitelisted field name; ``op`` is the
    resolved match strategy; ``value`` is the raw user operand (quotes and any
    trailing prefix ``*`` already stripped). This object holds no SQL — the
    resolver compiles it per field.
    """

    field: str
    op: Op
    value: str


def _validate_genre_value(value: str) -> None:
    """Reject non-canonical genres at parse time (mirrors ``get_books_by_genre``)."""
    if not is_canonical_genre(value):
        valid = ", ".join(CANONICAL_GENRES)
        raise CollectionQueryError(f"'{value}' is not a canonical genre. Valid genres: {valid}.")


def _validate_int_value(value: str) -> None:
    """Reject non-integer ``id`` operands."""
    try:
        int(value)
    except ValueError as exc:
        raise CollectionQueryError(f"'{value}' is not a valid integer id.") from exc


@dataclass(frozen=True)
class FieldSpec:
    """Capabilities of a whitelisted query field.

    ``match`` is the default op for a word/phrase value (``EQ`` for single-valued
    columns, ``CONTAINS`` for free-text people/subject columns). ``allow_prefix``
    permits the left-anchored ``value*`` form. ``validate`` runs against the raw
    value at parse time so an invalid query never reaches the resolver.
    """

    match: Op
    allow_prefix: bool = False
    validate: Callable[[str], None] | None = None


# The query field whitelist. This registry drives both the parser (validation and
# op resolution) and the resolver's per-field SQL compiler, which keys off these
# names. Later sub-slices grow this map (ranges/comparisons, booleans) without
# changing the ``parse_collection_query`` entry point.
QUERY_FIELDS: dict[str, FieldSpec] = {
    "id": FieldSpec(match=Op.EQ, validate=_validate_int_value),
    "title": FieldSpec(match=Op.EQ, allow_prefix=True),
    "author": FieldSpec(match=Op.CONTAINS),
    "series": FieldSpec(match=Op.EQ),
    "genre": FieldSpec(match=Op.EQ, validate=_validate_genre_value),
    "tag": FieldSpec(match=Op.EQ),
    "language": FieldSpec(match=Op.EQ),
    "publisher": FieldSpec(match=Op.EQ),
    "subject": FieldSpec(match=Op.CONTAINS),
    "isbn": FieldSpec(match=Op.EQ),
}
QUERY_FIELD_NAMES: tuple[str, ...] = tuple(QUERY_FIELDS)

_FIELD_LIST = ", ".join(QUERY_FIELD_NAMES)
_SYNTAX_MSG = (
    f"Invalid query syntax. Use a single term like 'genre:\"Science Fiction\"', "
    f"'series:Dune', or 'author:Tolkien' (valid fields: {_FIELD_LIST})."
)
_SINGLE_TERM_MSG = (
    f"Only a single field:value term is supported in this release "
    f"(e.g. 'author:Tolkien'). Boolean/range queries are not yet supported. "
    f"Valid fields: {_FIELD_LIST}."
)
_UNSUPPORTED_VALUE_MSG = (
    "Wildcards (except a trailing '*' on title), ranges, and comparisons are not "
    "supported in this release — use an exact field:value, e.g. 'series:Dune'."
)


def parse_collection_query(raw: str) -> QueryTerm:
    """Parse and validate a rule-based collection query into the query IR.

    Parse-permissive, validate-restrictive: luqum parses the full Lucene grammar,
    then the AST is walked and anything outside the supported subset is rejected. A
    valid query is currently exactly one ``field:value`` / ``field:"phrase"`` /
    ``field:prefix*`` term over a whitelisted field.

    Raises:
        CollectionQueryError: on syntax errors, multi-term/boolean queries,
            unknown fields, unsupported value shapes (interior wildcards, ranges,
            comparisons), non-integer ids, or non-canonical genre values.
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

    return _validate_term(tree)


def _validate_term(node: SearchField) -> QueryTerm:
    """Validate one ``field:value`` SearchField against the whitelist into a QueryTerm."""
    field = node.name.lower()
    if field not in QUERY_FIELDS:
        raise CollectionQueryError(f"Unknown field '{node.name}'. Valid fields: {_FIELD_LIST}.")
    spec = QUERY_FIELDS[field]

    expr = node.expr
    if isinstance(expr, Phrase):
        value, op = _strip_quotes(expr.value), spec.match
    elif isinstance(expr, Word):
        value, op = _resolve_word(expr.value, spec)
    else:
        # Range, Fuzzy, Proximity, comparison, etc. — not in the current subset.
        raise CollectionQueryError(_UNSUPPORTED_VALUE_MSG)

    if spec.validate is not None:
        spec.validate(value)

    return QueryTerm(field=field, op=op, value=value)


def _resolve_word(raw_value: str, spec: FieldSpec) -> tuple[str, Op]:
    """Resolve a bare Word value to (value, op), handling the trailing-``*`` prefix form."""
    if raw_value.endswith("*") and "*" not in raw_value[:-1] and "?" not in raw_value:
        if not spec.allow_prefix:
            raise CollectionQueryError(_UNSUPPORTED_VALUE_MSG)
        return raw_value[:-1], Op.PREFIX
    if "*" in raw_value or "?" in raw_value:
        raise CollectionQueryError(_UNSUPPORTED_VALUE_MSG)
    return raw_value, spec.match


def _strip_quotes(phrase_value: str) -> str:
    """Strip the surrounding double quotes luqum keeps on a Phrase's value."""
    if len(phrase_value) >= 2 and phrase_value[0] == '"' and phrase_value[-1] == '"':
        return phrase_value[1:-1]
    return phrase_value

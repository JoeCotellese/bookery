# ABOUTME: Parses and validates rule-based collection queries into a small query IR.
# ABOUTME: Pure module — owns the luqum dependency, no DB import; SQL lives in the resolver.

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from luqum.exceptions import ParseError
from luqum.parser import parser
from luqum.tree import From, Phrase, Range, SearchField, To, Word

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
    RANGE = "range"  # bounded interval (``year:[2000 TO 2010]``)
    GE = "ge"  # >=
    GT = "gt"  # >
    LE = "le"  # <=
    LT = "lt"  # <


@dataclass(frozen=True)
class QueryTerm:
    """A validated single-field leaf of the query IR.

    ``field`` is a canonical, lower-cased whitelisted field name; ``op`` is the
    resolved match strategy. For scalar ops (EQ/CONTAINS/PREFIX/GE/GT/LE/LT)
    ``value`` carries the raw operand (quotes and any trailing prefix ``*`` already
    stripped). For ``RANGE`` ``value`` is None and ``low``/``high`` carry the bounds
    (None = open-ended) with their inclusivity flags. This object holds no SQL —
    the resolver compiles it per field.
    """

    field: str
    op: Op
    value: str | None = None
    low: str | None = None
    high: str | None = None
    include_low: bool = True
    include_high: bool = True


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


def _validate_year_value(value: str) -> None:
    """Reject non-integer ``year`` operands."""
    try:
        int(value)
    except ValueError as exc:
        raise CollectionQueryError(
            f"'{value}' is not a valid year (use a 4-digit year like 2020)."
        ) from exc


def _validate_rating_value(value: str) -> None:
    """Reject non-numeric ``rating`` operands."""
    try:
        float(value)
    except ValueError as exc:
        raise CollectionQueryError(
            f"'{value}' is not a valid rating (use a number like 4 or 4.5)."
        ) from exc


def _validate_iso_date_value(value: str) -> None:
    """Reject ``added`` operands that are not ISO 8601 calendar dates."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise CollectionQueryError(
            f"'{value}' is not a valid ISO date (use YYYY-MM-DD, e.g. 2024-01-31)."
        ) from exc


@dataclass(frozen=True)
class FieldSpec:
    """Capabilities of a whitelisted query field.

    ``match`` is the default op for a word/phrase value (``EQ`` for single-valued
    columns, ``CONTAINS`` for free-text people/subject columns). ``allow_prefix``
    permits the left-anchored ``value*`` form. ``allow_range`` permits ranges
    (``[a TO b]``) and comparisons (``>=``/``<=``/``>``/``<``) — numeric/date fields
    only. ``validate`` runs against the raw value (and each range bound) at parse
    time so an invalid query never reaches the resolver.
    """

    match: Op
    allow_prefix: bool = False
    allow_range: bool = False
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
    "year": FieldSpec(match=Op.EQ, allow_range=True, validate=_validate_year_value),
    "rating": FieldSpec(match=Op.EQ, allow_range=True, validate=_validate_rating_value),
    "added": FieldSpec(match=Op.EQ, allow_range=True, validate=_validate_iso_date_value),
}
QUERY_FIELD_NAMES: tuple[str, ...] = tuple(QUERY_FIELDS)
_RANGE_FIELD_NAMES: tuple[str, ...] = tuple(f for f, s in QUERY_FIELDS.items() if s.allow_range)

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
    "Unsupported value. Use an exact field:value (e.g. 'series:Dune'), a trailing "
    "'*' prefix on title, or a range/comparison on a numeric/date field."
)
_RANGE_FIELD_MSG = (
    f"Ranges ([a TO b]) and comparisons (>=, <=, >, <) are only supported on the "
    f"numeric/date fields: {', '.join(_RANGE_FIELD_NAMES)}."
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
        value = _strip_quotes(expr.value)
        _apply_validator(spec, value)
        return QueryTerm(field=field, op=spec.match, value=value)
    if isinstance(expr, Word):
        value, op = _resolve_word(expr.value, spec)
        _apply_validator(spec, value)
        return QueryTerm(field=field, op=op, value=value)
    if isinstance(expr, Range):
        return _build_range_term(field, spec, expr)
    if isinstance(expr, From | To):
        return _build_comparison_term(field, spec, expr)
    # Fuzzy, Proximity, etc. — not in the supported subset.
    raise CollectionQueryError(_UNSUPPORTED_VALUE_MSG)


def _apply_validator(spec: FieldSpec, value: str) -> None:
    """Run the field's value validator (if any) against a raw operand."""
    if spec.validate is not None:
        spec.validate(value)


def _build_range_term(field: str, spec: FieldSpec, expr: Range) -> QueryTerm:
    """Validate a ``[a TO b]`` / ``{a TO b}`` range into a RANGE QueryTerm."""
    if not spec.allow_range:
        raise CollectionQueryError(_RANGE_FIELD_MSG)
    low = _range_bound(expr.low.value)
    high = _range_bound(expr.high.value)
    for bound in (low, high):
        if bound is not None:
            _apply_validator(spec, bound)
    return QueryTerm(
        field=field,
        op=Op.RANGE,
        low=low,
        high=high,
        include_low=expr.include_low,
        include_high=expr.include_high,
    )


def _range_bound(raw: str) -> str | None:
    """A luqum range bound; ``*`` means open-ended (None)."""
    return None if raw == "*" else raw


def _build_comparison_term(field: str, spec: FieldSpec, expr: From | To) -> QueryTerm:
    """Validate a ``>=``/``>``/``<=``/``<`` comparison into a GE/GT/LE/LT QueryTerm."""
    if not spec.allow_range:
        raise CollectionQueryError(_RANGE_FIELD_MSG)
    value = expr.a.value
    _apply_validator(spec, value)
    if isinstance(expr, From):
        op = Op.GE if expr.include else Op.GT
    else:  # To
        op = Op.LE if expr.include else Op.LT
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

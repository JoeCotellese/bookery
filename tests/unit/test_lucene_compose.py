# ABOUTME: Unit tests for the pure Lucene clause composer (collections/lucene_compose.py).
# ABOUTME: Asserts quoting rules and the round-trip invariant — every composed clause parses.

import pytest

from bookery.collections import (
    QUERY_FIELD_NAMES,
    append_clause,
    parse_collection_query,
    quote_value,
)

# A battery of field-valid values to feed the round-trip invariant. Each value is
# legal for its field (canonical genre, numeric rating/year, ISO date, integer id);
# the free-text fields get nasty values (spaces, quotes, colons, brackets) that must
# survive quoting and still parse.
_VALID_VALUES: dict[str, list[str]] = {
    "id": ["5", "42"],
    "title": ["Dune", "The Lord of the Rings", "Dune: Part One", 'Say "Hello"', "C++ [Primer]"],
    "author": ["Tolkien", "Frank Herbert", "O'Brien, Patrick", "Strunk & White"],
    "series": ["Dune", "A Song of Ice & Fire"],
    "genre": ["Science Fiction", "Fantasy"],
    "tag": ["favorite", "to-read", "sci fi"],
    "language": ["en", "pt-BR"],
    "publisher": ["Tor", "Penguin (UK)", "Farrar, Straus and Giroux"],
    "subject": ["Space opera", "Coming of age: a study"],
    "isbn": ["9780441013593", "978-0-441-01359-3"],
    "year": ["2020", "1999"],
    "rating": ["4", "4.5"],
    "added": ["2020-01-01", "2026-05-31"],
}


class TestQuoteValue:
    def test_simple_token_stays_bare(self):
        assert quote_value("Dune") == "Dune"
        assert quote_value("Tolkien") == "Tolkien"

    def test_numeric_token_stays_bare(self):
        assert quote_value("2020") == "2020"
        assert quote_value("5") == "5"

    def test_underscore_token_stays_bare(self):
        assert quote_value("to_read") == "to_read"

    def test_value_with_space_becomes_phrase(self):
        assert quote_value("Frank Herbert") == '"Frank Herbert"'

    def test_value_with_colon_becomes_phrase(self):
        assert quote_value("Dune: Part One") == '"Dune: Part One"'

    def test_value_with_bracket_becomes_phrase(self):
        assert quote_value("[Primer]") == '"[Primer]"'

    def test_hyphenated_value_becomes_phrase(self):
        # A bare hyphen would read as a Lucene prohibit operator, so quote it.
        assert quote_value("to-read") == '"to-read"'

    def test_embedded_double_quote_is_escaped(self):
        assert quote_value('Say "Hi"') == '"Say \\"Hi\\""'

    def test_embedded_backslash_is_escaped(self):
        assert quote_value("a\\b") == '"a\\\\b"'

    def test_reserved_word_is_quoted(self):
        # AND/OR/NOT/TO are Lucene keywords; bare emission would be ambiguous.
        for word in ["AND", "or", "Not", "to"]:
            assert quote_value(word) == f'"{word}"'


class TestAppendClause:
    def test_empty_existing_has_no_leading_operator(self):
        assert append_clause("", "series", "Dune") == "series:Dune"

    def test_blank_existing_is_treated_as_empty(self):
        assert append_clause("   ", "series", "Dune") == "series:Dune"

    def test_non_empty_existing_joined_with_and(self):
        result = append_clause("series:Dune", "author", "Frank Herbert")
        assert result == 'series:Dune AND author:"Frank Herbert"'

    def test_custom_operator_respected(self):
        result = append_clause("series:Dune", "genre", "Fantasy", op="OR")
        assert result == "series:Dune OR genre:Fantasy"

    def test_quotes_value_with_special_chars(self):
        assert append_clause("", "title", "Dune: Part One") == 'title:"Dune: Part One"'


class TestRoundTripInvariant:
    """Every composed clause must parse cleanly against the engine."""

    @pytest.mark.parametrize("field", QUERY_FIELD_NAMES)
    def test_single_clause_parses(self, field):
        for value in _VALID_VALUES[field]:
            clause = append_clause("", field, value)
            # Must not raise CollectionQueryError.
            parse_collection_query(clause)

    @pytest.mark.parametrize("field", QUERY_FIELD_NAMES)
    def test_appended_clause_parses(self, field):
        # Start from a known-valid clause, then append the field's nasty values.
        existing = "series:Dune"
        for value in _VALID_VALUES[field]:
            clause = append_clause(existing, field, value)
            parse_collection_query(clause)

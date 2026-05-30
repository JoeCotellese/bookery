# ABOUTME: Unit tests for the pure collections query parser/validator module.
# ABOUTME: Covers the slice-3 single-field equality subset and its error UX.

import pytest

from bookery.collections import (
    CollectionQuery,
    CollectionQueryError,
    parse_collection_query,
)
from bookery.metadata.genres import CANONICAL_GENRES


class TestValidQueries:
    def test_quoted_phrase_value(self) -> None:
        cq = parse_collection_query('genre:"Science Fiction"')
        assert cq == CollectionQuery(field="genre", value="Science Fiction")

    def test_bare_word_value(self) -> None:
        cq = parse_collection_query("series:Dune")
        assert cq == CollectionQuery(field="series", value="Dune")

    def test_series_quoted_multiword(self) -> None:
        cq = parse_collection_query('series:"The Lord of the Rings"')
        assert cq.field == "series"
        assert cq.value == "The Lord of the Rings"

    def test_field_name_is_case_insensitive(self) -> None:
        cq = parse_collection_query('GENRE:"Science Fiction"')
        assert cq.field == "genre"

    def test_genre_value_is_case_insensitive(self) -> None:
        # Canonical match is case-insensitive; the raw value is preserved.
        cq = parse_collection_query('genre:"science fiction"')
        assert cq.field == "genre"
        assert cq.value == "science fiction"

    def test_surrounding_whitespace_is_ignored(self) -> None:
        cq = parse_collection_query("  series:Dune  ")
        assert cq == CollectionQuery(field="series", value="Dune")


class TestFieldValidation:
    def test_unknown_field_lists_whitelist(self) -> None:
        with pytest.raises(CollectionQueryError) as exc:
            parse_collection_query("publisher:Tor")
        msg = str(exc.value)
        assert "publisher" in msg
        assert "series" in msg and "genre" in msg

    def test_author_returns_slice4_deferral(self) -> None:
        with pytest.raises(CollectionQueryError) as exc:
            parse_collection_query('author:"Frank Herbert"')
        msg = str(exc.value)
        assert "#236" in msg
        # Must be the specific deferral, not the generic unknown-field error.
        assert "Unknown field" not in msg

    def test_non_canonical_genre_lists_valid_genres(self) -> None:
        with pytest.raises(CollectionQueryError) as exc:
            parse_collection_query('genre:"Borg Romance"')
        msg = str(exc.value)
        assert "Borg Romance" in msg
        # A sampling of canonical genres should be named in the message.
        assert "Science Fiction" in msg
        assert all(g in msg for g in CANONICAL_GENRES)


class TestRejectedShapes:
    def test_multi_term_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("genre:SF series:Y")

    def test_explicit_and_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query('genre:"Science Fiction" AND series:Dune')

    def test_explicit_or_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query('genre:"Science Fiction" OR genre:Fantasy')

    def test_explicit_not_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("NOT genre:Horror")

    def test_bare_term_without_field_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("Dune")

    def test_wildcard_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("series:Sci*")

    def test_range_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("series:[a TO b]")

    def test_empty_query_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("")

    def test_garbage_syntax_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("genre:")

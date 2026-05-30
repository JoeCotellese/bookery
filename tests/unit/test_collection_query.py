# ABOUTME: Unit tests for the pure collections query parser/validator module.
# ABOUTME: Covers the scalar-field subset (exact/contains/prefix) and its error UX.

import pytest

from bookery.collections import (
    CollectionQueryError,
    Op,
    QueryTerm,
    parse_collection_query,
)
from bookery.metadata.genres import CANONICAL_GENRES


class TestExactFields:
    def test_quoted_phrase_value(self) -> None:
        cq = parse_collection_query('genre:"Science Fiction"')
        assert cq == QueryTerm(field="genre", op=Op.EQ, value="Science Fiction")

    def test_bare_word_value(self) -> None:
        cq = parse_collection_query("series:Dune")
        assert cq == QueryTerm(field="series", op=Op.EQ, value="Dune")

    def test_series_quoted_multiword(self) -> None:
        cq = parse_collection_query('series:"The Lord of the Rings"')
        assert cq.field == "series"
        assert cq.value == "The Lord of the Rings"

    def test_language_field(self) -> None:
        cq = parse_collection_query("language:en")
        assert cq == QueryTerm(field="language", op=Op.EQ, value="en")

    def test_publisher_field(self) -> None:
        cq = parse_collection_query("publisher:Tor")
        assert cq == QueryTerm(field="publisher", op=Op.EQ, value="Tor")

    def test_tag_field(self) -> None:
        cq = parse_collection_query("tag:favorites")
        assert cq == QueryTerm(field="tag", op=Op.EQ, value="favorites")

    def test_isbn_field(self) -> None:
        cq = parse_collection_query("isbn:9780441013593")
        assert cq == QueryTerm(field="isbn", op=Op.EQ, value="9780441013593")

    def test_id_field(self) -> None:
        cq = parse_collection_query("id:42")
        assert cq == QueryTerm(field="id", op=Op.EQ, value="42")

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
        assert cq == QueryTerm(field="series", op=Op.EQ, value="Dune")


class TestContainsFields:
    def test_author_is_contains(self) -> None:
        cq = parse_collection_query("author:Tolkien")
        assert cq == QueryTerm(field="author", op=Op.CONTAINS, value="Tolkien")

    def test_author_phrase_is_contains(self) -> None:
        cq = parse_collection_query('author:"J.R.R. Tolkien"')
        assert cq == QueryTerm(field="author", op=Op.CONTAINS, value="J.R.R. Tolkien")

    def test_subject_is_contains(self) -> None:
        cq = parse_collection_query("subject:dystopia")
        assert cq == QueryTerm(field="subject", op=Op.CONTAINS, value="dystopia")


class TestPrefix:
    def test_title_prefix(self) -> None:
        cq = parse_collection_query("title:Dune*")
        assert cq == QueryTerm(field="title", op=Op.PREFIX, value="Dune")

    def test_title_exact(self) -> None:
        cq = parse_collection_query('title:"Children of Dune"')
        assert cq == QueryTerm(field="title", op=Op.EQ, value="Children of Dune")

    def test_prefix_on_non_prefix_field_is_rejected(self) -> None:
        # Only title supports prefix in this release; series does not.
        with pytest.raises(CollectionQueryError):
            parse_collection_query("series:Sci*")

    def test_interior_wildcard_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("title:Du*ne")

    def test_question_mark_wildcard_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("title:Dun?")


class TestFieldValidation:
    def test_unknown_field_lists_whitelist(self) -> None:
        with pytest.raises(CollectionQueryError) as exc:
            parse_collection_query("nonsense:x")
        msg = str(exc.value)
        assert "nonsense" in msg
        # The whitelist should be advertised in the error.
        assert "series" in msg and "genre" in msg and "author" in msg

    def test_non_canonical_genre_lists_valid_genres(self) -> None:
        with pytest.raises(CollectionQueryError) as exc:
            parse_collection_query('genre:"Borg Romance"')
        msg = str(exc.value)
        assert "Borg Romance" in msg
        assert "Science Fiction" in msg
        assert all(g in msg for g in CANONICAL_GENRES)

    def test_id_non_integer_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("id:abc")


class TestStillRejected:
    """Shapes that land in later sub-slices remain rejected for now."""

    def test_explicit_and_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query('genre:"Science Fiction" AND series:Dune')

    def test_explicit_or_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query('genre:"Science Fiction" OR genre:Fantasy')

    def test_explicit_not_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("NOT genre:Horror")

    def test_implicit_multi_term_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("genre:SF series:Y")

    def test_range_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("year:[2000 TO 2010]")

    def test_comparison_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("rating:>=4")

    def test_bare_term_without_field_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("Dune")

    def test_empty_query_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("")

    def test_garbage_syntax_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("genre:")

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


class TestRangesAndComparisons:
    def test_inclusive_range(self) -> None:
        cq = parse_collection_query("year:[2000 TO 2010]")
        assert cq == QueryTerm(
            field="year",
            op=Op.RANGE,
            low="2000",
            high="2010",
            include_low=True,
            include_high=True,
        )

    def test_exclusive_range(self) -> None:
        cq = parse_collection_query("year:{2000 TO 2010}")
        assert cq == QueryTerm(
            field="year",
            op=Op.RANGE,
            low="2000",
            high="2010",
            include_low=False,
            include_high=False,
        )

    def test_open_upper_range(self) -> None:
        cq = parse_collection_query("year:[2020 TO *]")
        assert cq == QueryTerm(field="year", op=Op.RANGE, low="2020", high=None)

    def test_open_lower_range(self) -> None:
        cq = parse_collection_query("year:[* TO 2010]")
        assert cq == QueryTerm(field="year", op=Op.RANGE, low=None, high="2010")

    def test_ge_comparison(self) -> None:
        assert parse_collection_query("rating:>=4") == QueryTerm(
            field="rating", op=Op.GE, value="4"
        )

    def test_gt_comparison(self) -> None:
        assert parse_collection_query("rating:>4") == QueryTerm(
            field="rating", op=Op.GT, value="4"
        )

    def test_le_comparison(self) -> None:
        assert parse_collection_query("rating:<=5") == QueryTerm(
            field="rating", op=Op.LE, value="5"
        )

    def test_lt_comparison(self) -> None:
        assert parse_collection_query("rating:<2") == QueryTerm(
            field="rating", op=Op.LT, value="2"
        )

    def test_fractional_rating(self) -> None:
        assert parse_collection_query("rating:>=4.5") == QueryTerm(
            field="rating", op=Op.GE, value="4.5"
        )

    def test_year_equality_still_works(self) -> None:
        assert parse_collection_query("year:2020") == QueryTerm(
            field="year", op=Op.EQ, value="2020"
        )

    def test_added_iso_date_range(self) -> None:
        cq = parse_collection_query("added:[2024-01-01 TO 2024-12-31]")
        assert cq == QueryTerm(field="added", op=Op.RANGE, low="2024-01-01", high="2024-12-31")


class TestRangeValidation:
    def test_range_on_non_comparable_field_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError) as exc:
            parse_collection_query("series:[a TO b]")
        # The message should name the comparable fields.
        assert "year" in str(exc.value) and "rating" in str(exc.value)

    def test_comparison_on_non_comparable_field_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("title:>=4")

    def test_non_integer_year_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("year:twenty")

    def test_non_numeric_rating_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("rating:>=high")

    def test_bad_added_date_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("added:2024-13-99")

    def test_range_bound_is_validated(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("year:[abc TO 2010]")


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

    def test_bare_term_without_field_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("Dune")

    def test_empty_query_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("")

    def test_garbage_syntax_is_rejected(self) -> None:
        with pytest.raises(CollectionQueryError):
            parse_collection_query("genre:")

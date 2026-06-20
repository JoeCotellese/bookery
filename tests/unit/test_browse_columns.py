# ABOUTME: Unit tests for the list-view column-visibility helpers in web.browse.
# ABOUTME: Covers allow-list coercion and cookie parsing (absent vs empty vs values).

from bookery.web.browse import (
    DEFAULT_VISIBLE_COLUMNS,
    TOGGLEABLE_COLUMNS,
    coerce_columns,
    parse_columns_cookie,
)


class TestToggleableColumns:
    def test_default_visible_is_subset_of_toggleable(self):
        keys = {key for key, _ in TOGGLEABLE_COLUMNS}
        assert keys >= DEFAULT_VISIBLE_COLUMNS

    def test_default_visible_is_added_and_enriched(self):
        assert frozenset({"added", "enriched"}) == DEFAULT_VISIBLE_COLUMNS


class TestCoerceColumns:
    def test_keeps_only_known_keys(self):
        assert coerce_columns(["isbn", "bogus", "added"]) == {"isbn", "added"}

    def test_empty_input_yields_empty_set(self):
        assert coerce_columns([]) == set()

    def test_drops_all_unknown(self):
        assert coerce_columns(["nope", "title", "author"]) == set()


class TestParseColumnsCookie:
    def test_none_means_use_default(self):
        # ``None`` (cookie absent) is distinct from "" (present but empty) so the
        # caller can fall back to DEFAULT_VISIBLE_COLUMNS only when truly unset.
        assert parse_columns_cookie(None) is None

    def test_empty_string_means_no_toggleable_columns(self):
        assert parse_columns_cookie("") == set()

    def test_parses_comma_list_and_filters_unknown(self):
        assert parse_columns_cookie("isbn,added,bogus") == {"isbn", "added"}

    def test_tolerates_whitespace(self):
        assert parse_columns_cookie(" isbn , publisher ") == {"isbn", "publisher"}

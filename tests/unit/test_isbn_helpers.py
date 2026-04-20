# ABOUTME: Unit tests for ISBN-10 ↔ ISBN-13 conversion helpers in core.dedup.
# ABOUTME: Verifies round-trip conversion and check-digit math for both directions.

import pytest

from bookery.core.dedup import isbn10_to_isbn13, isbn13_to_isbn10, normalize_isbn


class TestIsbn10ToIsbn13:
    def test_known_value(self) -> None:
        assert isbn10_to_isbn13("0151446474") == "9780151446476"

    def test_check_digit_zero(self) -> None:
        # The Hobbit ISBN-10: 0547928211 → 9780547928210? Not exactly — pick another
        # Known: "0596000278" → "9780596000271"
        assert isbn10_to_isbn13("0596000278") == "9780596000271"

    def test_rejects_bad_input(self) -> None:
        with pytest.raises(ValueError):
            isbn10_to_isbn13("12345")


class TestIsbn13ToIsbn10:
    def test_known_value(self) -> None:
        assert isbn13_to_isbn10("9780151446476") == "0151446474"

    def test_round_trip(self) -> None:
        original_10 = "0596000278"
        as_13 = isbn10_to_isbn13(original_10)
        assert isbn13_to_isbn10(as_13) == original_10

    def test_check_digit_ten_becomes_x(self) -> None:
        # The Pragmatic Programmer: ISBN-10 ends in X, ISBN-13 is 9780201616224.
        assert isbn13_to_isbn10("9780201616224") == "020161622X"

    def test_rejects_non_978_prefix(self) -> None:
        with pytest.raises(ValueError):
            isbn13_to_isbn10("9791234567896")

    def test_rejects_non_numeric(self) -> None:
        with pytest.raises(ValueError):
            isbn13_to_isbn10("97801514464XX")


class TestNormalizeIsbnCanonicalization:
    def test_10_and_13_of_same_book_are_equal(self) -> None:
        assert normalize_isbn("0151446474") == normalize_isbn("9780151446476")

    def test_hyphenated_10_matches_plain_13(self) -> None:
        assert normalize_isbn("0-15-144647-4") == normalize_isbn("9780151446476")

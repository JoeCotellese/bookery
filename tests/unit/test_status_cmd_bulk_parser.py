# ABOUTME: Unit tests for the parse_bulk_ids helper used by `bookery read --bulk-from`.
# ABOUTME: Covers blank-line, comment, whitespace, and bad-ID handling rules.

import pytest

from bookery.cli.commands.status_cmd import parse_bulk_ids


class TestParseBulkIds:
    def test_simple_ids_one_per_line(self) -> None:
        assert parse_bulk_ids("1\n2\n3\n") == [1, 2, 3]

    def test_skips_blank_lines(self) -> None:
        assert parse_bulk_ids("1\n\n2\n\n\n3\n") == [1, 2, 3]

    def test_strips_whitespace(self) -> None:
        assert parse_bulk_ids("  1  \n\t 2\n3\t\n") == [1, 2, 3]

    def test_skips_full_line_comments(self) -> None:
        text = "# import wave 1\n1\n# wave 2\n2\n3\n"
        assert parse_bulk_ids(text) == [1, 2, 3]

    def test_skips_indented_comments(self) -> None:
        # A line that's whitespace then '#' is still a comment.
        text = "1\n   # interlude\n2\n"
        assert parse_bulk_ids(text) == [1, 2]

    def test_empty_input_returns_empty_list(self) -> None:
        assert parse_bulk_ids("") == []
        assert parse_bulk_ids("\n\n\n") == []
        assert parse_bulk_ids("# only comments\n# nothing else\n") == []

    def test_bad_id_raises_with_line_number_and_content(self) -> None:
        # Bad IDs surface the offending line so the user can fix the file
        # rather than guess. Line numbers are 1-based to match editor reality.
        text = "1\n2\nnot-an-id\n4\n"
        with pytest.raises(ValueError) as exc:
            parse_bulk_ids(text)
        msg = str(exc.value)
        assert "3" in msg  # line number
        assert "not-an-id" in msg  # offending content

    def test_negative_id_rejected(self) -> None:
        # Book IDs are positive autoincrement; a negative value is a typo.
        with pytest.raises(ValueError):
            parse_bulk_ids("1\n-3\n")

    def test_zero_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_bulk_ids("1\n0\n")

    def test_floating_point_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_bulk_ids("1\n2.5\n")

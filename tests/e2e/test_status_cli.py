# ABOUTME: End-to-end tests for `bookery mark finished|reading|unread`, and the
# ABOUTME: `ls --reading/--finished/--unread` filters plus info Reading section.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli


def _import_one(runner: CliRunner, db_path: Path, sample_epub: Path) -> None:
    """Import the standard sample EPUB into ``db_path`` and assert success."""
    result = runner.invoke(cli, ["import", str(sample_epub.parent), "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "1 added" in result.output


class TestStatusAuthoring:
    def test_mark_read_then_unread_then_reading(self, sample_epub: Path, tmp_path: Path) -> None:
        """Round-trip the three status verbs on a single book."""
        db_path = tmp_path / "status.db"
        runner = CliRunner()
        _import_one(runner, db_path, sample_epub)

        # Mark finished — title should appear in confirmation.
        result = runner.invoke(cli, ["mark", "finished", "1", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Marked" in result.output
        assert "finished" in result.output
        assert "Name of the Rose" in result.output

        # Mark unread.
        result = runner.invoke(cli, ["mark", "unread", "1", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "unread" in result.output

        # Mark in-progress.
        result = runner.invoke(cli, ["mark", "reading", "1", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "reading" in result.output

    def test_unknown_book_id_errors(self, sample_epub: Path, tmp_path: Path) -> None:
        db_path = tmp_path / "status.db"
        runner = CliRunner()
        _import_one(runner, db_path, sample_epub)

        result = runner.invoke(cli, ["mark", "finished", "999", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "999" in result.output

    def test_missing_argument_errors_cleanly(self, tmp_path: Path) -> None:
        db_path = tmp_path / "status.db"
        runner = CliRunner()
        # Empty DB but the command should still fail at usage validation.
        result = runner.invoke(cli, ["mark", "finished", "--db", str(db_path)])
        assert result.exit_code != 0
        assert "BOOK_ID" in result.output or "bulk-from" in result.output

    def test_book_id_and_bulk_from_are_mutually_exclusive(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "status.db"
        runner = CliRunner()
        _import_one(runner, db_path, sample_epub)
        bulk = tmp_path / "ids.txt"
        bulk.write_text("1\n")

        result = runner.invoke(
            cli, ["mark", "finished", "1", "--bulk-from", str(bulk), "--db", str(db_path)]
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output


class TestBulkFrom:
    def test_bulk_from_marks_multiple(self, sample_epub: Path, tmp_path: Path) -> None:
        db_path = tmp_path / "bulk.db"
        runner = CliRunner()
        _import_one(runner, db_path, sample_epub)

        bulk = tmp_path / "ids.txt"
        bulk.write_text("# bulk wave 1\n1\n\n# trailing comment\n")

        result = runner.invoke(
            cli, ["mark", "finished", "--bulk-from", str(bulk), "--db", str(db_path)]
        )
        assert result.exit_code == 0
        assert "1 book(s) as finished" in result.output

    def test_bulk_from_warns_on_unknown_id_and_continues(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "bulk-bad.db"
        runner = CliRunner()
        _import_one(runner, db_path, sample_epub)

        bulk = tmp_path / "ids.txt"
        bulk.write_text("1\n999\n")
        result = runner.invoke(
            cli, ["mark", "finished", "--bulk-from", str(bulk), "--db", str(db_path)]
        )
        assert result.exit_code == 0
        assert "Skipped 999" in result.output
        assert "1 book(s) as finished" in result.output

    def test_bulk_from_bad_id_format_errors(self, sample_epub: Path, tmp_path: Path) -> None:
        db_path = tmp_path / "bulk-format.db"
        runner = CliRunner()
        _import_one(runner, db_path, sample_epub)

        bulk = tmp_path / "ids.txt"
        bulk.write_text("1\nnot-a-number\n")
        result = runner.invoke(
            cli, ["mark", "finished", "--bulk-from", str(bulk), "--db", str(db_path)]
        )
        assert result.exit_code != 0
        assert "not-a-number" in result.output


class TestInfoReadingSection:
    def test_info_shows_reading_section_after_mark(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "info.db"
        runner = CliRunner()
        _import_one(runner, db_path, sample_epub)
        runner.invoke(cli, ["mark", "finished", "1", "--db", str(db_path)])

        result = runner.invoke(cli, ["info", "1", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Reading" in result.output  # the section header
        assert "Finished" in result.output  # the status name

    def test_info_no_reading_section_when_no_data(self, sample_epub: Path, tmp_path: Path) -> None:
        db_path = tmp_path / "info-clean.db"
        runner = CliRunner()
        _import_one(runner, db_path, sample_epub)

        result = runner.invoke(cli, ["info", "1", "--db", str(db_path)])
        assert result.exit_code == 0
        # No section header; the Rich table title for the metadata table has
        # no "Reading" string, so plain absence is the right assertion.
        assert "Reading\n" not in result.output


class TestLsStatusFilters:
    def test_ls_finished_includes_finished_excludes_others(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "lsfilters.db"
        runner = CliRunner()
        _import_one(runner, db_path, sample_epub)
        runner.invoke(cli, ["mark", "finished", "1", "--db", str(db_path)])

        result = runner.invoke(cli, ["ls", "--finished", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Name of the Rose" in result.output

        result = runner.invoke(cli, ["ls", "--reading", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Name of the Rose" not in result.output

        result = runner.invoke(cli, ["ls", "--unread", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Name of the Rose" not in result.output

    def test_ls_unread_includes_books_with_no_status_row(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "lsunread.db"
        runner = CliRunner()
        _import_one(runner, db_path, sample_epub)

        result = runner.invoke(cli, ["ls", "--unread", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Name of the Rose" in result.output

    def test_ls_unread_includes_books_marked_unread(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "lsunread2.db"
        runner = CliRunner()
        _import_one(runner, db_path, sample_epub)
        runner.invoke(cli, ["mark", "finished", "1", "--db", str(db_path)])
        runner.invoke(cli, ["mark", "unread", "1", "--db", str(db_path)])

        result = runner.invoke(cli, ["ls", "--unread", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Name of the Rose" in result.output

    def test_status_filters_are_mutually_exclusive(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "lsmutex.db"
        runner = CliRunner()
        _import_one(runner, db_path, sample_epub)

        result = runner.invoke(cli, ["ls", "--finished", "--reading", "--db", str(db_path)])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower() or "only one" in result.output.lower()

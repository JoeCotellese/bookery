# ABOUTME: End-to-end tests for the `bookery tag` CLI command group.
# ABOUTME: Tests full tag workflow via Click's CliRunner with real database.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli


class TestTagCliE2E:
    """E2E tests for the tag CLI workflow."""

    def test_full_tag_lifecycle(self, sample_epub: Path, tmp_path: Path) -> None:
        """Full lifecycle: import → tag add → tag ls → info shows tag → tag rm."""
        db_path = tmp_path / "e2e.db"
        runner = CliRunner()

        # Import a book
        result = runner.invoke(cli, ["import", str(sample_epub.parent), "--db", str(db_path)])
        assert result.exit_code == 0
        assert "1 added" in result.output

        # Tag the book
        result = runner.invoke(cli, ["tag", "add", "1", "classic", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "classic" in result.output

        # Add another tag
        result = runner.invoke(cli, ["tag", "add", "1", "adventure", "--db", str(db_path)])
        assert result.exit_code == 0

        # List tags
        result = runner.invoke(cli, ["tag", "ls", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "classic" in result.output
        assert "adventure" in result.output

        # Info shows tags
        result = runner.invoke(cli, ["info", "1", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "classic" in result.output
        assert "adventure" in result.output

        # ls --tag filters correctly
        result = runner.invoke(cli, ["ls", "--tag", "classic", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "The Name of the Rose" in result.output

        # Remove a tag
        result = runner.invoke(cli, ["tag", "rm", "1", "adventure", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Removed" in result.output

        # Verify adventure is gone from tags row
        result = runner.invoke(cli, ["info", "1", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "adventure" not in result.output
        assert "classic" in result.output

    def test_tag_add_duplicate_is_safe(self, sample_epub: Path, tmp_path: Path) -> None:
        """Adding the same tag twice doesn't cause errors."""
        db_path = tmp_path / "dup.db"
        runner = CliRunner()

        runner.invoke(cli, ["import", str(sample_epub.parent), "--db", str(db_path)])

        result = runner.invoke(cli, ["tag", "add", "1", "fiction", "--db", str(db_path)])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["tag", "add", "1", "fiction", "--db", str(db_path)])
        assert result.exit_code == 0

    def test_tag_operations_on_missing_book(self, tmp_path: Path) -> None:
        """Tag operations on nonexistent books fail gracefully."""
        db_path = tmp_path / "nobook.db"
        runner = CliRunner()

        # Create empty DB
        result = runner.invoke(cli, ["tag", "ls", "--db", str(db_path)])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["tag", "add", "999", "fiction", "--db", str(db_path)])
        assert result.exit_code == 1

# ABOUTME: Spot-checks that key command one-line summaries name their input scope.
# ABOUTME: A user reading `bookery --help` should know what kind of input each command takes.

from click.testing import CliRunner

from bookery.cli import cli


def _help_line_for(command: str) -> str:
    """Return the first non-empty body line of `bookery <command> --help`."""
    runner = CliRunner()
    result = runner.invoke(cli, [command, "--help"])
    assert result.exit_code == 0, result.output
    # Click prints `Usage: ...` then a blank line then the docstring.
    lines = [line.strip() for line in result.output.splitlines()]
    saw_blank = False
    for line in lines:
        if not line:
            saw_blank = True
            continue
        if saw_blank:
            return line
    raise AssertionError(f"Could not find body line for {command!r}")


class TestTopLevelSummariesNameInputScope:
    """Each top-level command's first-line summary names what it operates on."""

    def test_info_mentions_both_id_and_disk(self) -> None:
        line = _help_line_for("info")
        # Catalog ID and loose-EPUB-on-disk are the two paths.
        assert "ID" in line
        assert "disk" in line.lower() or "loose" in line.lower()

    def test_match_clarifies_loose_files(self) -> None:
        line = _help_line_for("match")
        # Contrast with rematch — match operates on files not yet cataloged.
        assert "loose" in line.lower() or "not yet" in line.lower()

    def test_rematch_mentions_cataloged(self) -> None:
        line = _help_line_for("rematch")
        assert "catalog" in line.lower()

    def test_convert_mentions_input_scope(self) -> None:
        line = _help_line_for("convert")
        # Must indicate that input can be a single file or a directory.
        assert "directory" in line.lower() or "file or" in line.lower()

    def test_add_mentions_file_and_directory(self) -> None:
        line = _help_line_for("add")
        assert "file" in line.lower() or "EPUB" in line
        assert "directory" in line.lower()

    def test_reveal_mentions_id_or_title(self) -> None:
        line = _help_line_for("reveal")
        assert "ID" in line
        assert "title" in line.lower()

    def test_ls_mentions_library(self) -> None:
        line = _help_line_for("ls")
        assert "catalog" in line.lower() or "library" in line.lower()

    def test_inventory_mentions_directory(self) -> None:
        line = _help_line_for("inventory")
        assert "directory" in line.lower()

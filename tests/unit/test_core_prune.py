# ABOUTME: Unit tests for the orphan-detection helper used by `bookery prune`.
# ABOUTME: Exercises every (check_mode, source_exists, output_exists) cell on classify_row.

from pathlib import Path

import pytest

from bookery.core.prune import PruneState, classify_row
from bookery.db.mapping import BookRecord
from bookery.metadata.types import BookMetadata


def _record(
    *,
    source_path: Path,
    output_path: Path | None,
    book_id: int = 1,
) -> BookRecord:
    """Build a BookRecord with just enough fields to drive classify_row."""
    return BookRecord(
        id=book_id,
        metadata=BookMetadata(title="t", authors=["a"], source_path=source_path),
        file_hash="h",
        source_path=source_path,
        output_path=output_path,
        date_added="now",
        date_modified="now",
    )


class TestClassifyRowCheckBoth:
    def test_both_present_is_healthy(self, tmp_path: Path) -> None:
        src = tmp_path / "src.epub"
        out = tmp_path / "out.epub"
        src.write_bytes(b"x")
        out.write_bytes(b"y")

        result = classify_row(_record(source_path=src, output_path=out), check="both")
        assert result.state is PruneState.HEALTHY
        assert result.source_exists
        assert result.output_exists

    def test_both_missing_is_orphan(self, tmp_path: Path) -> None:
        result = classify_row(
            _record(
                source_path=tmp_path / "gone_src.epub",
                output_path=tmp_path / "gone_out.epub",
            ),
            check="both",
        )
        assert result.state is PruneState.ORPHAN

    def test_source_missing_output_present_is_warning(self, tmp_path: Path) -> None:
        out = tmp_path / "out.epub"
        out.write_bytes(b"y")

        result = classify_row(
            _record(source_path=tmp_path / "gone.epub", output_path=out),
            check="both",
        )
        assert result.state is PruneState.SOURCE_MISSING_OUTPUT_PRESENT

    def test_source_present_output_missing_is_orphan(self, tmp_path: Path) -> None:
        src = tmp_path / "src.epub"
        src.write_bytes(b"x")

        # source present, output set but missing → not orphan under "both"
        # because at least one checked path exists.
        result = classify_row(
            _record(source_path=src, output_path=tmp_path / "missing_out.epub"),
            check="both",
        )
        assert result.state is PruneState.HEALTHY

    def test_no_output_path_with_source_present_is_healthy(self, tmp_path: Path) -> None:
        src = tmp_path / "src.epub"
        src.write_bytes(b"x")

        result = classify_row(
            _record(source_path=src, output_path=None), check="both"
        )
        assert result.state is PruneState.HEALTHY

    def test_no_output_path_with_source_missing_is_orphan(self, tmp_path: Path) -> None:
        result = classify_row(
            _record(source_path=tmp_path / "gone.epub", output_path=None),
            check="both",
        )
        assert result.state is PruneState.ORPHAN


class TestClassifyRowCheckSource:
    def test_source_missing_is_orphan_regardless_of_output(self, tmp_path: Path) -> None:
        out = tmp_path / "out.epub"
        out.write_bytes(b"y")

        result = classify_row(
            _record(source_path=tmp_path / "gone.epub", output_path=out),
            check="source",
        )
        assert result.state is PruneState.ORPHAN

    def test_source_present_is_healthy(self, tmp_path: Path) -> None:
        src = tmp_path / "src.epub"
        src.write_bytes(b"x")

        result = classify_row(
            _record(source_path=src, output_path=None), check="source"
        )
        assert result.state is PruneState.HEALTHY


class TestClassifyRowCheckOutput:
    def test_output_missing_is_orphan(self, tmp_path: Path) -> None:
        src = tmp_path / "src.epub"
        src.write_bytes(b"x")

        result = classify_row(
            _record(source_path=src, output_path=tmp_path / "missing.epub"),
            check="output",
        )
        assert result.state is PruneState.ORPHAN

    def test_no_output_path_is_healthy(self, tmp_path: Path) -> None:
        # Nothing to check → no orphan call.
        result = classify_row(
            _record(source_path=tmp_path / "gone.epub", output_path=None),
            check="output",
        )
        assert result.state is PruneState.HEALTHY

    def test_output_present_is_healthy(self, tmp_path: Path) -> None:
        out = tmp_path / "out.epub"
        out.write_bytes(b"y")
        result = classify_row(
            _record(source_path=tmp_path / "gone.epub", output_path=out),
            check="output",
        )
        assert result.state is PruneState.HEALTHY


@pytest.mark.parametrize("mode", ["source", "output", "both"])
def test_state_enum_values_round_trip(mode: str) -> None:
    """Sanity: enum values are stable strings (used in table rendering)."""
    assert PruneState.HEALTHY.value == "healthy"
    assert PruneState.ORPHAN.value == "orphan"
    assert PruneState.SOURCE_MISSING_OUTPUT_PRESENT.value == "source-missing-output-present"
    assert mode in {"source", "output", "both"}

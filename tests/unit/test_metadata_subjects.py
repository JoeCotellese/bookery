# ABOUTME: Unit tests for the subjects field on BookMetadata.
# ABOUTME: Validates default value and construction with subjects.

from bookery.metadata.types import BookMetadata


class TestBookMetadataSubjects:
    """Tests for the subjects field on BookMetadata."""

    def test_default_subjects_is_empty_list(self) -> None:
        """BookMetadata defaults subjects to an empty list."""
        meta = BookMetadata(title="Test")
        assert meta.subjects == []

    def test_construct_with_subjects(self) -> None:
        """BookMetadata can be constructed with a list of subjects."""
        subjects = ["Fiction", "Mystery", "Historical"]
        meta = BookMetadata(title="Test", subjects=subjects)
        assert meta.subjects == ["Fiction", "Mystery", "Historical"]

    def test_subjects_is_independent_per_instance(self) -> None:
        """Each instance gets its own subjects list (no shared mutable default)."""
        meta1 = BookMetadata(title="A")
        meta2 = BookMetadata(title="B")
        meta1.subjects.append("Fiction")
        assert meta2.subjects == []

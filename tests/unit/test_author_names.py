# ABOUTME: Unit tests for the pure author-name logic (classify/canonical/key).
# ABOUTME: No DB — exercises reorder safety, collision keys, and tier routing.

import pytest

from bookery.metadata.author_names import (
    author_key,
    canonical_author,
    classify,
)


class TestClassify:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Cussler, Clive", "reorderable"),
            ("Sanderson, Brandon", "reorderable"),
            ("Clive Cussler", "ok"),
            ("Brandon Sanderson", "ok"),
            ("Plato", "mononym"),
            ("Homer", "mononym"),
            ("Vook", "mononym"),
            # Two full names joined by a comma — multiple people, not Last, First.
            ("Mikhail Sakhniuk, Adam Boduch", "blob"),
            # Credential tails never auto-reorder.
            ("Patricia McConnell, Ph.D.,", "credential"),
            ("Martin Luther King, Jr.", "credential"),
            # Compound surname is ambiguous -> route to manual merge, don't guess.
            ("García Márquez, Gabriel", "blob"),
            # Two commas -> blob.
            ("Smith, John, Jane", "blob"),
            ("", "ok"),
        ],
    )
    def test_classify(self, name: str, expected: str) -> None:
        assert classify(name) == expected


class TestCanonicalAuthor:
    def test_reorders_last_first(self) -> None:
        assert canonical_author("Cussler, Clive") == "Clive Cussler"
        assert canonical_author("Sanderson, Brandon") == "Brandon Sanderson"

    def test_leaves_already_normal(self) -> None:
        assert canonical_author("Clive Cussler") == "Clive Cussler"

    def test_leaves_mononym(self) -> None:
        assert canonical_author("Plato") == "Plato"

    def test_leaves_blob_and_credential(self) -> None:
        assert canonical_author("Mikhail Sakhniuk, Adam Boduch") == (
            "Mikhail Sakhniuk, Adam Boduch"
        )
        assert canonical_author("Patricia McConnell, Ph.D.,") == (
            "Patricia McConnell, Ph.D.,"
        )

    def test_strips_surrounding_whitespace(self) -> None:
        assert canonical_author("  Cussler,  Clive  ") == "Clive Cussler"


class TestAuthorKey:
    def test_reordered_and_plain_collide(self) -> None:
        assert author_key("Cussler, Clive") == author_key("Clive Cussler")

    def test_distinct_people_keep_distinct_keys(self) -> None:
        # Never group by first name — these are two different Bryans.
        assert author_key("Bryan Burrough") != author_key("Bryan Eisenberg")

    def test_son_is_not_the_father(self) -> None:
        assert author_key("Dirk Cussler") != author_key("Clive Cussler")

    def test_case_and_whitespace_insensitive(self) -> None:
        assert author_key("clive   cussler") == author_key("Clive Cussler")

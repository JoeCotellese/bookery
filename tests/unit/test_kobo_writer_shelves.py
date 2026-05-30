# ABOUTME: Unit tests for kobo_writer Shelf/ShelfContent operations against the real schema.
# ABOUTME: Validates write_collection_shelves and delete_orphan_shelves on a device-faithful DB.

from pathlib import Path

import pytest

from bookery.device.kobo_writer import (
    CollectionShelfUpdate,
    delete_orphan_shelves,
    write_collection_shelves,
)
from tests.fixtures.kobo_schema import connect_ro, make_fake_kobo_db, seed_shelf

NOW = "2024-01-15T10:30:00"


@pytest.fixture()
def kobo_db_path(tmp_path: Path) -> Path:
    """A fake Kobo DB with the real Shelf/ShelfContent schema."""
    return make_fake_kobo_db(tmp_path)


def _content_ids_for(db_path: Path, shelf_key: str) -> list[str]:
    """ContentIds linked to a shelf. ``shelf_key`` is the InternalName (the value
    ShelfContent.ShelfName holds), not the display name."""
    conn = connect_ro(db_path)
    try:
        rows = conn.execute(
            "SELECT ContentId FROM ShelfContent WHERE ShelfName = ? ORDER BY ContentId",
            (shelf_key,),
        ).fetchall()
    finally:
        conn.close()
    return [row["ContentId"] for row in rows]


class TestWriteCollectionShelves:
    def test_creates_shelf_and_content(self, kobo_db_path: Path) -> None:
        """A single update creates a Shelf row and its ShelfContent rows."""
        updates = [
            CollectionShelfUpdate(
                shelf_id="shelf-uuid-1",
                internal_name="bookery-7",
                shelf_name="Sci-Fi",
                content_ids=[
                    "file:///mnt/onboard/Bookery/A/A.kepub.epub",
                    "file:///mnt/onboard/Bookery/B/B.kepub.epub",
                ],
            )
        ]

        report = write_collection_shelves(db_path=kobo_db_path, updates=updates, now=lambda: NOW)

        assert report.pushed_count == 1
        assert report.failed == []
        assert report.skipped == []

        conn = connect_ro(kobo_db_path)
        shelf = conn.execute(
            "SELECT * FROM Shelf WHERE InternalName = ?", ("bookery-7",)
        ).fetchone()
        conn.close()

        assert shelf is not None
        assert shelf["Id"] == "shelf-uuid-1"
        assert shelf["Name"] == "Sci-Fi"
        assert shelf["Type"] == "UserTag"
        # Booleans stored as the text values Kobo uses, not integers. nickel
        # only renders shelves/content marked _IsSynced='true'; 'false' rows
        # are treated as un-reconciled local edits and suppressed in the UI.
        assert shelf["_IsDeleted"] == "false"
        assert shelf["_IsVisible"] == "true"
        assert shelf["_IsSynced"] == "true"

        # ShelfContent links by InternalName (what nickel joins on), not the
        # display name — so membership is keyed on "bookery-7", not "Sci-Fi".
        assert _content_ids_for(kobo_db_path, "bookery-7") == [
            "file:///mnt/onboard/Bookery/A/A.kepub.epub",
            "file:///mnt/onboard/Bookery/B/B.kepub.epub",
        ]
        assert _content_ids_for(kobo_db_path, "Sci-Fi") == []

    def test_rerun_replaces_membership(self, kobo_db_path: Path) -> None:
        """Re-pushing the same shelf reflects added and removed books."""
        first = [
            CollectionShelfUpdate(
                shelf_id="shelf-uuid-1",
                internal_name="bookery-7",
                shelf_name="Sci-Fi",
                content_ids=["file:///mnt/onboard/Bookery/A/A.kepub.epub"],
            )
        ]
        write_collection_shelves(db_path=kobo_db_path, updates=first, now=lambda: NOW)

        second = [
            CollectionShelfUpdate(
                shelf_id="shelf-uuid-1",
                internal_name="bookery-7",
                shelf_name="Sci-Fi",
                content_ids=[
                    "file:///mnt/onboard/Bookery/B/B.kepub.epub",
                    "file:///mnt/onboard/Bookery/C/C.kepub.epub",
                ],
            )
        ]
        write_collection_shelves(db_path=kobo_db_path, updates=second, now=lambda: NOW)

        assert _content_ids_for(kobo_db_path, "bookery-7") == [
            "file:///mnt/onboard/Bookery/B/B.kepub.epub",
            "file:///mnt/onboard/Bookery/C/C.kepub.epub",
        ]
        # Exactly one Shelf row for our InternalName, not a duplicate.
        conn = connect_ro(kobo_db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM Shelf WHERE InternalName = ?", ("bookery-7",)
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_rename_keeps_membership_under_internal_name(self, kobo_db_path: Path) -> None:
        """Renaming a collection updates the display Name but keeps membership.

        Because ShelfContent is keyed on the stable InternalName, a rename never
        strands content under an old name.
        """
        write_collection_shelves(
            db_path=kobo_db_path,
            updates=[
                CollectionShelfUpdate(
                    shelf_id="shelf-uuid-1",
                    internal_name="bookery-7",
                    shelf_name="Old Name",
                    content_ids=["file:///mnt/onboard/Bookery/A/A.kepub.epub"],
                )
            ],
            now=lambda: NOW,
        )
        write_collection_shelves(
            db_path=kobo_db_path,
            updates=[
                CollectionShelfUpdate(
                    shelf_id="shelf-uuid-1",
                    internal_name="bookery-7",
                    shelf_name="New Name",
                    content_ids=["file:///mnt/onboard/Bookery/A/A.kepub.epub"],
                )
            ],
            now=lambda: NOW,
        )

        # Membership stays under the InternalName; display name updates.
        assert _content_ids_for(kobo_db_path, "bookery-7") == [
            "file:///mnt/onboard/Bookery/A/A.kepub.epub"
        ]
        conn = connect_ro(kobo_db_path)
        name = conn.execute(
            "SELECT Name FROM Shelf WHERE InternalName = 'bookery-7'"
        ).fetchone()["Name"]
        conn.close()
        assert name == "New Name"

    def test_collision_guard_skips_foreign_shelf(self, kobo_db_path: Path) -> None:
        """A user shelf sharing the target name is left untouched and reported."""
        seed_shelf(
            kobo_db_path,
            shelf_id="user-xyz",
            name="Sci-Fi",
            internal_name="Sci-Fi",  # user shelf: InternalName == Name, not 'bookery-*'
        )

        report = write_collection_shelves(
            db_path=kobo_db_path,
            updates=[
                CollectionShelfUpdate(
                    shelf_id="shelf-uuid-1",
                    internal_name="bookery-7",
                    shelf_name="Sci-Fi",
                    content_ids=["file:///mnt/onboard/Bookery/A/A.kepub.epub"],
                )
            ],
            now=lambda: NOW,
        )

        assert report.pushed_count == 0
        assert len(report.skipped) == 1
        assert report.skipped[0][0] == "Sci-Fi"

        conn = connect_ro(kobo_db_path)
        # The user's shelf still exists; no bookery- shelf was created.
        user = conn.execute("SELECT Id FROM Shelf WHERE Name = 'Sci-Fi'").fetchall()
        ours = conn.execute("SELECT Id FROM Shelf WHERE InternalName = 'bookery-7'").fetchall()
        conn.close()
        assert len(user) == 1
        assert user[0]["Id"] == "user-xyz"
        assert ours == []

    def test_does_not_touch_unrelated_user_shelves(self, kobo_db_path: Path) -> None:
        """Pushing a bookery shelf leaves differently-named user shelves intact."""
        seed_shelf(kobo_db_path, shelf_id="u1", name="Fiction", internal_name="Fiction")

        write_collection_shelves(
            db_path=kobo_db_path,
            updates=[
                CollectionShelfUpdate(
                    shelf_id="shelf-uuid-1",
                    internal_name="bookery-7",
                    shelf_name="Sci-Fi",
                    content_ids=["file:///mnt/onboard/Bookery/A/A.kepub.epub"],
                )
            ],
            now=lambda: NOW,
        )

        conn = connect_ro(kobo_db_path)
        fiction = conn.execute("SELECT Id FROM Shelf WHERE Name = 'Fiction'").fetchone()
        conn.close()
        assert fiction is not None
        assert fiction["Id"] == "u1"

    def test_empty_updates_returns_empty(self, kobo_db_path: Path) -> None:
        report = write_collection_shelves(db_path=kobo_db_path, updates=[], now=lambda: NOW)
        assert report.pushed_count == 0
        assert report.failed == []
        assert report.skipped == []


class TestDeleteOrphanShelves:
    def test_removes_orphaned_bookery_shelf(self, kobo_db_path: Path) -> None:
        """A bookery- shelf no longer valid is removed with its content."""
        write_collection_shelves(
            db_path=kobo_db_path,
            updates=[
                CollectionShelfUpdate(
                    shelf_id="s1",
                    internal_name="bookery-1",
                    shelf_name="Keep",
                    content_ids=["file:///mnt/onboard/Bookery/A/A.kepub.epub"],
                ),
                CollectionShelfUpdate(
                    shelf_id="s2",
                    internal_name="bookery-2",
                    shelf_name="Drop",
                    content_ids=["file:///mnt/onboard/Bookery/B/B.kepub.epub"],
                ),
            ],
            now=lambda: NOW,
        )

        deleted = delete_orphan_shelves(db_path=kobo_db_path, valid_internal_names={"bookery-1"})

        assert deleted == ["Drop"]
        conn = connect_ro(kobo_db_path)
        remaining = {
            row["InternalName"]
            for row in conn.execute("SELECT InternalName FROM Shelf").fetchall()
        }
        drop_content = conn.execute(
            "SELECT COUNT(*) FROM ShelfContent WHERE ShelfName = 'bookery-2'"
        ).fetchone()[0]
        conn.close()
        assert remaining == {"bookery-1"}
        assert drop_content == 0

    def test_leaves_user_shelves_untouched(self, kobo_db_path: Path) -> None:
        """Orphan cleanup never deletes non-bookery shelves."""
        seed_shelf(kobo_db_path, shelf_id="u1", name="Fiction", internal_name="Fiction")

        deleted = delete_orphan_shelves(db_path=kobo_db_path, valid_internal_names=set())

        assert deleted == []
        conn = connect_ro(kobo_db_path)
        fiction = conn.execute("SELECT Id FROM Shelf WHERE Name = 'Fiction'").fetchone()
        conn.close()
        assert fiction is not None

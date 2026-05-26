# ABOUTME: Unit tests for discover_existing_device_files — the pre-pull phase
# ABOUTME: that reconciles device_files against what's actually on the mount.

from dataclasses import dataclass, field
from pathlib import Path

from bookery.db.mapping import BookRecord
from bookery.device.kobo import discover_existing_device_files
from bookery.metadata.types import BookMetadata


@dataclass
class _StubCatalog:
    upsert_calls: list[dict] = field(default_factory=list)

    def upsert_device_file(
        self, *, device_id: int, book_id: int, remote_path: str, now: str
    ) -> None:
        self.upsert_calls.append(
            {
                "device_id": device_id,
                "book_id": book_id,
                "remote_path": remote_path,
                "now": now,
            }
        )


def _record(
    *, rec_id: int, title: str, author: str, output_path: Path | None
) -> BookRecord:
    metadata = BookMetadata(title=title, authors=[author] if author else [])
    return BookRecord(
        id=rec_id,
        metadata=metadata,
        file_hash="hash",
        source_path=output_path or Path("/missing.epub"),
        output_path=output_path,
        date_added="2026-04-18T00:00:00",
        date_modified="2026-04-18T00:00:00",
    )


def _seed_on_device(
    target: Path, books_subdir: str, author: str, title: str, body: bytes = b"x"
) -> Path:
    # Mirror bookery's layout: <root>/<subdir>/<Author>/<Title>/<Title>.kepub.epub
    dest = target / books_subdir / author / title / f"{title}.kepub.epub"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return dest


def test_upserts_device_file_for_each_existing_book(tmp_path: Path) -> None:
    target = tmp_path / "kobo"
    target.mkdir()
    _seed_on_device(target, "Bookery", "Asimov", "Foundation")
    _seed_on_device(target, "Bookery", "Le Guin", "Earthsea")

    catalog = _StubCatalog()
    records = [
        _record(
            rec_id=1,
            title="Foundation",
            author="Asimov",
            output_path=tmp_path / "lib" / "a.epub",
        ),
        _record(
            rec_id=2,
            title="Earthsea",
            author="Le Guin",
            output_path=tmp_path / "lib" / "b.epub",
        ),
    ]

    discovered = discover_existing_device_files(
        catalog,
        records=records,
        target=target,
        books_subdir="Bookery",
        device_id=7,
        now="2026-05-26T16:30:00",
    )

    assert discovered == 2
    assert len(catalog.upsert_calls) == 2
    by_book = {call["book_id"]: call for call in catalog.upsert_calls}
    assert (
        by_book[1]["remote_path"]
        == "/mnt/onboard/Bookery/Asimov/Foundation/Foundation.kepub.epub"
    )
    assert (
        by_book[2]["remote_path"]
        == "/mnt/onboard/Bookery/Le Guin/Earthsea/Earthsea.kepub.epub"
    )
    assert all(call["device_id"] == 7 for call in catalog.upsert_calls)
    assert all(call["now"] == "2026-05-26T16:30:00" for call in catalog.upsert_calls)


def test_skips_records_whose_dest_file_is_absent(tmp_path: Path) -> None:
    target = tmp_path / "kobo"
    target.mkdir()
    # Only "Foundation" is actually on the device.
    _seed_on_device(target, "Bookery", "Asimov", "Foundation")

    catalog = _StubCatalog()
    records = [
        _record(
            rec_id=1,
            title="Foundation",
            author="Asimov",
            output_path=tmp_path / "lib" / "a.epub",
        ),
        _record(
            rec_id=2,
            title="Earthsea",
            author="Le Guin",
            output_path=tmp_path / "lib" / "b.epub",
        ),
    ]

    discovered = discover_existing_device_files(
        catalog,
        records=records,
        target=target,
        books_subdir="Bookery",
        device_id=7,
        now="2026-05-26T16:30:00",
    )

    assert discovered == 1
    assert [call["book_id"] for call in catalog.upsert_calls] == [1]


def test_skips_records_with_no_output_path(tmp_path: Path) -> None:
    target = tmp_path / "kobo"
    target.mkdir()
    # Seed a file at the path bookery would compute for the record — even so,
    # a record with no output_path is not in the library and must not be
    # claimed as if bookery had put it there.
    _seed_on_device(target, "Bookery", "Asimov", "Foundation")

    catalog = _StubCatalog()
    records = [
        _record(rec_id=1, title="Foundation", author="Asimov", output_path=None),
    ]

    discovered = discover_existing_device_files(
        catalog,
        records=records,
        target=target,
        books_subdir="Bookery",
        device_id=7,
        now="2026-05-26T16:30:00",
    )

    assert discovered == 0
    assert catalog.upsert_calls == []


def test_returns_zero_when_target_is_empty(tmp_path: Path) -> None:
    target = tmp_path / "kobo"
    target.mkdir()

    catalog = _StubCatalog()
    records = [
        _record(
            rec_id=1,
            title="Foundation",
            author="Asimov",
            output_path=tmp_path / "lib" / "a.epub",
        ),
    ]

    discovered = discover_existing_device_files(
        catalog,
        records=records,
        target=target,
        books_subdir="Bookery",
        device_id=7,
        now="2026-05-26T16:30:00",
    )

    assert discovered == 0
    assert catalog.upsert_calls == []

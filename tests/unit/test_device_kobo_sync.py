# ABOUTME: Unit tests for sync_library_to_kobo — orchestrates kepubify + cache + copy.
# ABOUTME: Stubs the kepubify wrapper and uses a real KepubCache + tmp filesystem.

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from bookery.db.mapping import BookRecord
from bookery.device.kepub_cache import KepubCache
from bookery.device.kobo import SyncReport, sync_library_to_kobo
from bookery.metadata.types import BookMetadata


class StubKepubify:
    """Test double for the kepubify subprocess wrapper."""

    def __init__(self, *, version: str = "v4.4.0", payload: bytes = b"FAKE-KEPUB") -> None:
        self.version = version
        self.payload = payload
        self.calls: list[tuple[Path, Path]] = []

    def run(self, epub: Path, *, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        result = out_dir / f"{epub.stem}.kepub.epub"
        result.write_bytes(self.payload)
        self.calls.append((epub, out_dir))
        return result

    def get_version(self) -> str:
        return self.version


@dataclass
class StubCatalog:
    records: list[BookRecord]
    device_id: int = 42
    device_files: dict[tuple[int, str], int] = field(default_factory=dict)
    upsert_device_calls: list[dict] = field(default_factory=list)
    upsert_device_file_calls: list[dict] = field(default_factory=list)
    read_state_upserts: list[dict] = field(default_factory=list)
    book_status_seeds: list[dict] = field(default_factory=list)

    def list_all(self) -> list[BookRecord]:
        return list(self.records)

    def upsert_device(self, *, kind: str, serial: str, label, now: str) -> int:
        self.upsert_device_calls.append(
            {"kind": kind, "serial": serial, "label": label, "now": now}
        )
        return self.device_id

    def upsert_device_file(
        self, *, device_id: int, book_id: int, remote_path: str, now: str
    ) -> None:
        self.upsert_device_file_calls.append(
            {
                "device_id": device_id,
                "book_id": book_id,
                "remote_path": remote_path,
                "now": now,
            }
        )
        self.device_files[(device_id, remote_path)] = book_id

    def resolve_book_id_for_remote_path(
        self, *, device_id: int, remote_path: str
    ) -> int | None:
        return self.device_files.get((device_id, remote_path))

    def upsert_device_read_state(self, **kwargs) -> None:
        self.read_state_upserts.append(kwargs)

    def merge_book_status_from_device(self, **kwargs) -> None:
        self.book_status_seeds.append(kwargs)

    def list_push_candidates(self, *, device_id: int) -> list:
        # Stub catalog never produces push candidates; the push phase
        # short-circuits without touching the device DB.
        return []


def _make_record(
    *,
    rec_id: int,
    title: str,
    author: str,
    epub_path: Path,
    file_hash: str = "deadbeef",
) -> BookRecord:
    metadata = BookMetadata(title=title, authors=[author] if author else [])
    return BookRecord(
        id=rec_id,
        metadata=metadata,
        file_hash=file_hash,
        source_path=epub_path,
        output_path=epub_path,
        date_added="2026-04-18T00:00:00",
        date_modified="2026-04-18T00:00:00",
    )


def _write_epub(path: Path, body: bytes = b"EPUB-CONTENT") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def _setup(tmp_path: Path, *, write_version: bool = True) -> dict[str, Any]:
    library = tmp_path / "library"
    target = tmp_path / "kobo"
    if write_version:
        kobo_dir = target / ".kobo"
        kobo_dir.mkdir(parents=True)
        (kobo_dir / "version").write_text("N428440071799,4.45.23684\n")
    cache = KepubCache(tmp_path / "kepub.db")
    kepubify = StubKepubify()
    workspace = tmp_path / "workspace"
    return {
        "library": library,
        "target": target,
        "cache": cache,
        "kepubify": kepubify,
        "workspace": workspace,
    }


def test_empty_catalog_returns_zero_actions(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    report = sync_library_to_kobo(
        catalog=StubCatalog(records=[]),
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
    )
    assert isinstance(report, SyncReport)
    assert report.copied == []
    assert report.skipped == []
    assert report.failed == []


def test_single_book_first_sync_runs_kepubify_and_copies(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    epub = env["library"] / "Author A" / "Title A" / "Title A.epub"
    _write_epub(epub)
    record = _make_record(
        rec_id=1, title="Title A", author="Author A", epub_path=epub
    )

    report = sync_library_to_kobo(
        catalog=StubCatalog(records=[record]),
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
    )

    expected_dest = (
        env["target"] / "Books" / "Author A" / "Title A" / "Title A.kepub.epub"
    )
    assert expected_dest.exists()
    assert expected_dest.read_bytes() == b"FAKE-KEPUB"
    assert report.copied == [expected_dest]
    assert report.skipped == []
    assert report.failed == []
    assert len(env["kepubify"].calls) == 1


def test_resync_with_unchanged_files_skips_kepubify(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    epub = env["library"] / "A" / "T" / "T.epub"
    _write_epub(epub)
    record = _make_record(rec_id=1, title="T", author="A", epub_path=epub)
    catalog = StubCatalog(records=[record])

    sync_library_to_kobo(
        catalog=catalog,
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
    )
    first_call_count = len(env["kepubify"].calls)

    report = sync_library_to_kobo(
        catalog=catalog,
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
    )

    assert len(env["kepubify"].calls) == first_call_count, (
        "kepubify should not be re-invoked when source hash, version and "
        "on-device hash all match."
    )
    assert len(report.skipped) == 1
    assert len(report.copied) == 0


def test_resync_with_missing_device_file_re_runs(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    epub = env["library"] / "A" / "T" / "T.epub"
    _write_epub(epub)
    record = _make_record(rec_id=1, title="T", author="A", epub_path=epub)
    catalog = StubCatalog(records=[record])

    first = sync_library_to_kobo(
        catalog=catalog,
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
    )
    dest = first.copied[0]
    dest.unlink()

    report = sync_library_to_kobo(
        catalog=catalog,
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
    )

    assert len(env["kepubify"].calls) == 2
    assert dest.exists()
    assert len(report.copied) == 1


def test_dry_run_makes_no_writes(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    epub = env["library"] / "A" / "T" / "T.epub"
    _write_epub(epub)
    record = _make_record(rec_id=1, title="T", author="A", epub_path=epub)

    report = sync_library_to_kobo(
        catalog=StubCatalog(records=[record]),
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
        dry_run=True,
    )

    assert env["kepubify"].calls == []
    assert not env["target"].exists() or not any(env["target"].rglob("*.kepub.epub"))
    assert len(report.copied) == 1, "dry-run should still report planned copies"


def test_record_without_output_path_is_skipped(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    metadata = BookMetadata(title="Orphan", authors=["Nobody"])
    record = BookRecord(
        id=1,
        metadata=metadata,
        file_hash="x",
        source_path=tmp_path / "missing.epub",
        output_path=None,
        date_added="",
        date_modified="",
    )

    report = sync_library_to_kobo(
        catalog=StubCatalog(records=[record]),
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
    )

    assert env["kepubify"].calls == []
    assert len(report.skipped) == 1
    _path, reason = report.skipped[0]
    assert "no canonical EPUB" in reason


def test_unknown_author_path_component(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    epub = env["library"] / "anon" / "Mystery.epub"
    _write_epub(epub)
    metadata = BookMetadata(title="Mystery", authors=[])
    record = BookRecord(
        id=1,
        metadata=metadata,
        file_hash="abc",
        source_path=epub,
        output_path=epub,
        date_added="",
        date_modified="",
    )

    sync_library_to_kobo(
        catalog=StubCatalog(records=[record]),
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
    )

    expected = (
        env["target"] / "Books" / "Unknown Author" / "Mystery" / "Mystery.kepub.epub"
    )
    assert expected.exists()


def test_non_epub_output_path_is_skipped(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    pdf = env["library"] / "A" / "T" / "T.pdf"
    _write_epub(pdf, body=b"%PDF")
    record = _make_record(rec_id=1, title="T", author="A", epub_path=pdf)

    report = sync_library_to_kobo(
        catalog=StubCatalog(records=[record]),
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
    )

    assert env["kepubify"].calls == []
    assert len(report.skipped) == 1
    _, reason = report.skipped[0]
    assert "not an EPUB" in reason or "epub" in reason.lower()


def test_on_stage_emits_full_lifecycle(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    epub = env["library"] / "A" / "T" / "T.epub"
    _write_epub(epub)
    record = _make_record(rec_id=1, title="T", author="A", epub_path=epub)
    catalog = StubCatalog(records=[record])

    stages: list[str] = []

    def on_stage(stage: str) -> None:
        stages.append(stage)

    sync_library_to_kobo(
        catalog=catalog,
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
        on_stage=on_stage,
    )

    # First sync: full pipeline.
    assert stages == ["hash", "convert", "copy", "done"]


def test_on_stage_emits_cached_when_skipping(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    epub = env["library"] / "A" / "T" / "T.epub"
    _write_epub(epub)
    record = _make_record(rec_id=1, title="T", author="A", epub_path=epub)
    catalog = StubCatalog(records=[record])

    # Prime the cache with a successful sync.
    sync_library_to_kobo(
        catalog=catalog,
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
    )

    stages: list[str] = []
    sync_library_to_kobo(
        catalog=catalog,
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
        on_stage=stages.append,
    )

    assert stages == ["hash", "cached"]


def test_on_progress_callback_invoked_per_record(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    epubs = []
    records = []
    for i in range(3):
        epub = env["library"] / f"A{i}" / f"T{i}" / f"T{i}.epub"
        _write_epub(epub)
        epubs.append(epub)
        records.append(_make_record(rec_id=i, title=f"T{i}", author=f"A{i}", epub_path=epub))

    seen: list[tuple[int, int, str]] = []

    def cb(idx: int, total: int, record):  # type: ignore[no-untyped-def]
        seen.append((idx, total, record.metadata.title))

    sync_library_to_kobo(
        catalog=StubCatalog(records=records),
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
        on_progress=cb,
    )

    assert seen == [
        (1, 3, "T0"),
        (2, 3, "T1"),
        (3, 3, "T2"),
    ]


def test_on_progress_callback_invoked_in_dry_run(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    epub = env["library"] / "A" / "T" / "T.epub"
    _write_epub(epub)
    record = _make_record(rec_id=1, title="T", author="A", epub_path=epub)

    seen: list[int] = []

    def cb(idx: int, total: int, _record) -> None:  # type: ignore[no-untyped-def]
        seen.append(idx)
        assert total == 1

    sync_library_to_kobo(
        catalog=StubCatalog(records=[record]),
        target=env["target"],
        cache=env["cache"],
        run_kepubify=env["kepubify"].run,
        kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
        books_subdir="Books",
        dry_run=True,
        on_progress=cb,
    )
    assert seen == [1]


def test_kepubify_failure_is_recorded_not_raised(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    epub = env["library"] / "A" / "T" / "T.epub"
    _write_epub(epub)
    record = _make_record(rec_id=1, title="T", author="A", epub_path=epub)

    def boom(_epub: Path, *, out_dir: Path) -> Path:
        raise RuntimeError("kepubify crashed")

    with pytest.MonkeyPatch.context():
        report = sync_library_to_kobo(
            catalog=StubCatalog(records=[record]),
            target=env["target"],
            cache=env["cache"],
            run_kepubify=boom,
            kepubify_version=env["kepubify"].get_version,
        workspace_dir=env["workspace"],
            books_subdir="Books",
        )

    assert len(report.failed) == 1
    assert "kepubify crashed" in report.failed[0][1]


class TestDeviceWiring:
    """The sync wiring added in P1a (issue #180).

    Read state pull runs before the kepub copy loop, device_files rows are
    written per successful copy, and a missing `.kobo/version` degrades
    gracefully (kepub copy still runs).
    """

    def test_device_upserted_before_loop(self, tmp_path: Path) -> None:
        env = _setup(tmp_path)
        epub = env["library"] / "A" / "T" / "T.epub"
        _write_epub(epub)
        record = _make_record(rec_id=1, title="T", author="A", epub_path=epub)
        catalog = StubCatalog(records=[record])

        sync_library_to_kobo(
            catalog=catalog,
            target=env["target"],
            cache=env["cache"],
            run_kepubify=env["kepubify"].run,
            kepubify_version=env["kepubify"].get_version,
            workspace_dir=env["workspace"],
            books_subdir="Books",
        )
        assert len(catalog.upsert_device_calls) == 1
        call = catalog.upsert_device_calls[0]
        assert call["kind"] == "kobo"
        assert call["serial"] == "N428440071799"

    def test_device_files_upserted_per_copy(self, tmp_path: Path) -> None:
        env = _setup(tmp_path)
        records = []
        for i in range(3):
            epub = env["library"] / f"A{i}" / f"T{i}" / f"T{i}.epub"
            _write_epub(epub)
            records.append(
                _make_record(rec_id=i + 1, title=f"T{i}", author=f"A{i}", epub_path=epub)
            )
        catalog = StubCatalog(records=records)

        sync_library_to_kobo(
            catalog=catalog,
            target=env["target"],
            cache=env["cache"],
            run_kepubify=env["kepubify"].run,
            kepubify_version=env["kepubify"].get_version,
            workspace_dir=env["workspace"],
            books_subdir="Books",
        )
        assert len(catalog.upsert_device_file_calls) == 3
        book_ids = {c["book_id"] for c in catalog.upsert_device_file_calls}
        assert book_ids == {1, 2, 3}
        # Recorded remote_paths are in the device coordinate system
        # (/mnt/onboard/...), not the host mount path — so they line up with
        # Kobo's ContentID format on real hardware.
        for call in catalog.upsert_device_file_calls:
            assert call["remote_path"].startswith("/mnt/onboard/Books/")
            assert call["remote_path"].endswith(".kepub.epub")
            assert call["device_id"] == catalog.device_id

    def test_no_device_file_upsert_when_copy_skipped(self, tmp_path: Path) -> None:
        env = _setup(tmp_path)
        epub = env["library"] / "A" / "T" / "T.epub"
        _write_epub(epub)
        record = _make_record(rec_id=1, title="T", author="A", epub_path=epub)
        catalog = StubCatalog(records=[record])

        # First sync — copies and records the device_file.
        sync_library_to_kobo(
            catalog=catalog,
            target=env["target"],
            cache=env["cache"],
            run_kepubify=env["kepubify"].run,
            kepubify_version=env["kepubify"].get_version,
            workspace_dir=env["workspace"],
            books_subdir="Books",
        )
        baseline = len(catalog.upsert_device_file_calls)

        # Second sync — kepub cache hits, file skipped; no new device_file row.
        sync_library_to_kobo(
            catalog=catalog,
            target=env["target"],
            cache=env["cache"],
            run_kepubify=env["kepubify"].run,
            kepubify_version=env["kepubify"].get_version,
            workspace_dir=env["workspace"],
            books_subdir="Books",
        )
        assert len(catalog.upsert_device_file_calls) == baseline

    def test_dry_run_does_not_touch_device_tables(self, tmp_path: Path) -> None:
        env = _setup(tmp_path)
        epub = env["library"] / "A" / "T" / "T.epub"
        _write_epub(epub)
        record = _make_record(rec_id=1, title="T", author="A", epub_path=epub)
        catalog = StubCatalog(records=[record])

        sync_library_to_kobo(
            catalog=catalog,
            target=env["target"],
            cache=env["cache"],
            run_kepubify=env["kepubify"].run,
            kepubify_version=env["kepubify"].get_version,
            workspace_dir=env["workspace"],
            books_subdir="Books",
            dry_run=True,
        )
        assert catalog.upsert_device_calls == []
        assert catalog.upsert_device_file_calls == []

    def test_sync_continues_when_kobo_version_missing(self, tmp_path: Path) -> None:
        env = _setup(tmp_path, write_version=False)
        epub = env["library"] / "A" / "T" / "T.epub"
        _write_epub(epub)
        record = _make_record(rec_id=1, title="T", author="A", epub_path=epub)
        catalog = StubCatalog(records=[record])

        report = sync_library_to_kobo(
            catalog=catalog,
            target=env["target"],
            cache=env["cache"],
            run_kepubify=env["kepubify"].run,
            kepubify_version=env["kepubify"].get_version,
            workspace_dir=env["workspace"],
            books_subdir="Books",
        )
        # The kepub copy still happens — sync is best-effort.
        assert len(report.copied) == 1
        # But no device-side bookkeeping was done (no serial → no device id).
        assert catalog.upsert_device_calls == []
        assert catalog.upsert_device_file_calls == []
        assert report.read_states_pulled == 0
        assert report.read_states_skipped == 0

    def test_report_has_read_state_counter_defaults(self, tmp_path: Path) -> None:
        env = _setup(tmp_path)
        catalog = StubCatalog(records=[])
        report = sync_library_to_kobo(
            catalog=catalog,
            target=env["target"],
            cache=env["cache"],
            run_kepubify=env["kepubify"].run,
            kepubify_version=env["kepubify"].get_version,
            workspace_dir=env["workspace"],
            books_subdir="Books",
        )
        assert report.read_states_pulled == 0
        assert report.read_states_skipped == 0

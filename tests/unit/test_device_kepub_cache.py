# ABOUTME: Unit tests for the kepub conversion cache used by Kobo sync.
# ABOUTME: Verifies key composition (source hash + kepubify version) and round-trip behavior.

from pathlib import Path

from bookery.device.kepub_cache import KepubCache


def test_get_returns_none_on_miss(tmp_path: Path) -> None:
    cache = KepubCache(tmp_path / "kepub.db")
    assert cache.get("source-hash", "v4.4.0") is None


def test_put_then_get_round_trip(tmp_path: Path) -> None:
    cache = KepubCache(tmp_path / "kepub.db")
    cache.put("source-hash", "v4.4.0", "kepub-sha", Path("/dev/A/T/T.kepub.epub"))
    assert cache.get("source-hash", "v4.4.0") == "kepub-sha"


def test_different_kepubify_version_misses(tmp_path: Path) -> None:
    cache = KepubCache(tmp_path / "kepub.db")
    cache.put("source-hash", "v4.4.0", "kepub-sha", Path("/dev/A/T/T.kepub.epub"))
    assert cache.get("source-hash", "v4.5.0") is None


def test_put_is_idempotent(tmp_path: Path) -> None:
    cache = KepubCache(tmp_path / "kepub.db")
    cache.put("source-hash", "v4.4.0", "first", Path("/dev/A/T/T.kepub.epub"))
    cache.put("source-hash", "v4.4.0", "second", Path("/dev/A/T/T.kepub.epub"))
    assert cache.get("source-hash", "v4.4.0") == "second"


def test_iter_entries_yields_device_paths(tmp_path: Path) -> None:
    cache = KepubCache(tmp_path / "kepub.db")
    p1 = Path("/dev/A/T1/T1.kepub.epub")
    p2 = Path("/dev/B/T2/T2.kepub.epub")
    cache.put("h1", "v4.4.0", "k1", p1)
    cache.put("h2", "v4.4.0", "k2", p2)
    entries = sorted(cache.iter_entries(), key=lambda e: e.source_hash)
    assert [e.device_path for e in entries] == [p1, p2]
    assert [e.kepub_sha for e in entries] == ["k1", "k2"]


def test_creates_parent_directory(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "dir" / "kepub.db"
    KepubCache(db)
    assert db.parent.exists()


def test_get_quickcheck_returns_none_on_miss(tmp_path: Path) -> None:
    cache = KepubCache(tmp_path / "kepub.db")
    assert cache.get_quickcheck("/lib/A/T/T.epub", "v4.4.0") is None


def test_record_then_get_quickcheck_round_trip(tmp_path: Path) -> None:
    cache = KepubCache(tmp_path / "kepub.db")
    cache.record_quickcheck(
        source_path="/lib/A/T/T.epub",
        kepubify_version="v4.4.0",
        source_size=100,
        source_mtime=1_700_000_000.0,
        dest_path="/dev/A/T/T.kepub.epub",
        dest_size=120,
        dest_mtime=1_700_000_500.0,
    )
    entry = cache.get_quickcheck("/lib/A/T/T.epub", "v4.4.0")
    assert entry is not None
    assert entry.source_size == 100
    assert entry.source_mtime == 1_700_000_000.0
    assert entry.dest_path == Path("/dev/A/T/T.kepub.epub")
    assert entry.dest_size == 120
    assert entry.dest_mtime == 1_700_000_500.0


def test_get_quickcheck_misses_on_version_change(tmp_path: Path) -> None:
    cache = KepubCache(tmp_path / "kepub.db")
    cache.record_quickcheck(
        source_path="/lib/A/T/T.epub",
        kepubify_version="v4.4.0",
        source_size=100,
        source_mtime=1_700_000_000.0,
        dest_path="/dev/A/T/T.kepub.epub",
        dest_size=120,
        dest_mtime=1_700_000_500.0,
    )
    assert cache.get_quickcheck("/lib/A/T/T.epub", "v4.5.0") is None


def test_record_quickcheck_overwrites_same_source_path(tmp_path: Path) -> None:
    cache = KepubCache(tmp_path / "kepub.db")
    cache.record_quickcheck(
        source_path="/lib/A/T/T.epub",
        kepubify_version="v4.4.0",
        source_size=100,
        source_mtime=1.0,
        dest_path="/dev/A/T/T.kepub.epub",
        dest_size=120,
        dest_mtime=2.0,
    )
    cache.record_quickcheck(
        source_path="/lib/A/T/T.epub",
        kepubify_version="v4.4.0",
        source_size=200,
        source_mtime=3.0,
        dest_path="/dev/A/T/T.kepub.epub",
        dest_size=220,
        dest_mtime=4.0,
    )
    entry = cache.get_quickcheck("/lib/A/T/T.epub", "v4.4.0")
    assert entry is not None
    assert entry.source_size == 200
    assert entry.dest_size == 220

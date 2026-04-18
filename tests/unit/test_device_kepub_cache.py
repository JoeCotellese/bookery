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

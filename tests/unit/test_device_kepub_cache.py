# ABOUTME: Unit tests for the kepub conversion cache used by Kobo sync.
# ABOUTME: Verifies key composition (source hash + kepubify version) and round-trip behavior.

from pathlib import Path

from bookery.device.kepub_cache import KepubCache


def test_get_returns_none_on_miss(tmp_path: Path) -> None:
    cache = KepubCache(tmp_path / "kepub.db")
    assert cache.get("source-hash", "v4.4.0") is None


def test_put_then_get_round_trip(tmp_path: Path) -> None:
    cache = KepubCache(tmp_path / "kepub.db")
    cache.put("source-hash", "v4.4.0", "kepub-sha")
    assert cache.get("source-hash", "v4.4.0") == "kepub-sha"


def test_different_kepubify_version_misses(tmp_path: Path) -> None:
    cache = KepubCache(tmp_path / "kepub.db")
    cache.put("source-hash", "v4.4.0", "kepub-sha")
    assert cache.get("source-hash", "v4.5.0") is None


def test_put_is_idempotent(tmp_path: Path) -> None:
    cache = KepubCache(tmp_path / "kepub.db")
    cache.put("source-hash", "v4.4.0", "first")
    cache.put("source-hash", "v4.4.0", "second")
    assert cache.get("source-hash", "v4.4.0") == "second"


def test_creates_parent_directory(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "dir" / "kepub.db"
    KepubCache(db)
    assert db.parent.exists()

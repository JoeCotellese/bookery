# ABOUTME: Unit tests for detect_mounted_kobo() — finds a mounted Kobo by .kobo/ marker.
# ABOUTME: Uses tmp_path to simulate volumes; no real device required.

from pathlib import Path

from bookery.device.kobo import detect_mounted_kobo


def _make_volume(root: Path, name: str, *, with_marker: bool) -> Path:
    vol = root / name
    vol.mkdir()
    if with_marker:
        (vol / ".kobo").mkdir()
    return vol


def test_returns_path_when_marker_present(tmp_path: Path) -> None:
    vol = _make_volume(tmp_path, "KOBOeReader", with_marker=True)
    assert detect_mounted_kobo(candidates=[vol]) == vol


def test_returns_none_when_no_marker(tmp_path: Path) -> None:
    vol = _make_volume(tmp_path, "USB", with_marker=False)
    assert detect_mounted_kobo(candidates=[vol]) is None


def test_returns_first_match_among_multiple(tmp_path: Path) -> None:
    vol1 = _make_volume(tmp_path, "USB", with_marker=False)
    vol2 = _make_volume(tmp_path, "KOBOeReader", with_marker=True)
    vol3 = _make_volume(tmp_path, "OtherKobo", with_marker=True)
    assert detect_mounted_kobo(candidates=[vol1, vol2, vol3]) == vol2


def test_skips_nonexistent_candidates(tmp_path: Path) -> None:
    vol = _make_volume(tmp_path, "KOBOeReader", with_marker=True)
    missing = tmp_path / "does-not-exist"
    assert detect_mounted_kobo(candidates=[missing, vol]) == vol


def test_scans_volumes_directories(tmp_path: Path, monkeypatch) -> None:
    """When candidates is None, scan default platform mount roots."""
    volumes = tmp_path / "Volumes"
    volumes.mkdir()
    _make_volume(volumes, "USB", with_marker=False)
    kobo = _make_volume(volumes, "KOBOeReader", with_marker=True)
    monkeypatch.setattr(
        "bookery.device.kobo._default_mount_roots", lambda: [volumes]
    )
    assert detect_mounted_kobo() == kobo

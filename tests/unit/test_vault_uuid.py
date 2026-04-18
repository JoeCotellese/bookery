# ABOUTME: Unit tests for deterministic EPUB identifier generation.
# ABOUTME: Stable mode must produce the same UUID across calls for the same vault path.

from pathlib import Path

from bookery.core.vault.epub import stable_uuid


def test_stable_uuid_is_deterministic(tmp_path: Path):
    u1 = stable_uuid(tmp_path)
    u2 = stable_uuid(tmp_path)
    assert u1 == u2


def test_different_paths_produce_different_uuids(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert stable_uuid(a) != stable_uuid(b)


def test_uuid_is_urn_prefixed():
    uid = stable_uuid(Path("/some/path"))
    assert uid.startswith("urn:uuid:")

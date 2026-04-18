# ABOUTME: Unit tests for the SQLite LLM response cache.

from pathlib import Path

from bookery.convert.cache import LLMCache, make_key


def test_make_key_deterministic() -> None:
    k1 = make_key(1, "qwen2.5-7b-instruct", "hello world")
    k2 = make_key(1, "qwen2.5-7b-instruct", "hello world")
    assert k1 == k2
    assert len(k1) == 64


def test_make_key_version_bump_invalidates() -> None:
    k1 = make_key(1, "m", "chunk")
    k2 = make_key(2, "m", "chunk")
    assert k1 != k2


def test_make_key_model_change_invalidates() -> None:
    k1 = make_key(1, "model-a", "chunk")
    k2 = make_key(1, "model-b", "chunk")
    assert k1 != k2


def test_make_key_text_change_invalidates() -> None:
    k1 = make_key(1, "m", "chunk one")
    k2 = make_key(1, "m", "chunk two")
    assert k1 != k2


def test_cache_roundtrip(tmp_path: Path) -> None:
    cache = LLMCache(tmp_path / "cache.db")
    cache.put("k", '{"hello": "world"}')
    assert cache.get("k") == '{"hello": "world"}'


def test_cache_miss_returns_none(tmp_path: Path) -> None:
    cache = LLMCache(tmp_path / "cache.db")
    assert cache.get("missing") is None


def test_cache_overwrite(tmp_path: Path) -> None:
    cache = LLMCache(tmp_path / "cache.db")
    cache.put("k", "first")
    cache.put("k", "second")
    assert cache.get("k") == "second"


def test_cache_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "cache.db"
    cache = LLMCache(path)
    cache.put("k", "v")
    assert path.exists()
    assert cache.get("k") == "v"


def test_cache_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    LLMCache(path).put("k", "v")
    assert LLMCache(path).get("k") == "v"

# ABOUTME: Unit tests for the [vault_export] section of bookery's config file.
# ABOUTME: Verifies defaults, folder lists, and index options round-trip through load_config.

from pathlib import Path

from bookery.core.config import load_config


def _write_config(tmp_path: Path, body: str) -> Path:
    cfg_dir = tmp_path / ".bookery"
    cfg_dir.mkdir()
    cfg = cfg_dir / "config.toml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_defaults_when_section_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, 'library_root = "/tmp/lib"\n')
    cfg = load_config()
    ve = cfg.vault_export
    assert ve.vault_path is None
    assert ve.folders == []
    assert ve.include_index is False
    assert ve.index_exclude_prefixes == []
    assert ve.index_min_count == 1
    assert ve.default_author == "Obsidian Vault"
    assert ve.uuid_mode == "stable"


def test_parses_vault_export_section(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(
        tmp_path,
        """
library_root = "/tmp/lib"

[vault_export]
vault_path = "~/obsidian"
folders = ["Permanent", "Literature"]
include_index = true
index_exclude_prefixes = ["type/"]
index_min_count = 2
default_author = "Joe"
uuid_mode = "random"
exclude_tags = ["type/meeting", "type/daily"]
""",
    )
    cfg = load_config()
    ve = cfg.vault_export
    assert ve.vault_path is not None
    assert str(ve.vault_path).endswith("obsidian")
    assert ve.folders == ["Permanent", "Literature"]
    assert ve.include_index is True
    assert ve.index_exclude_prefixes == ["type/"]
    assert ve.index_min_count == 2
    assert ve.default_author == "Joe"
    assert ve.uuid_mode == "random"
    assert ve.exclude_tags == ["type/meeting", "type/daily"]

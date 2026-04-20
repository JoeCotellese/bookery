# ABOUTME: Tests for [matching] config section (auto-accept threshold).
# ABOUTME: Verifies default, config-file override, and accessor.

from pathlib import Path

import pytest

from bookery.core import config as config_module


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("BOOKERY_LIBRARY_ROOT", raising=False)
    yield tmp_path


def test_default_auto_accept_threshold_is_08(isolated_home):
    assert config_module.load_config().matching.auto_accept_threshold == 0.8


def test_config_file_override(isolated_home):
    config_dir = isolated_home / ".bookery"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        'library_root = "/tmp/lib"\n'
        "[matching]\n"
        "auto_accept_threshold = 0.92\n"
    )
    assert config_module.load_config().matching.auto_accept_threshold == 0.92


def test_get_matching_config_accessor(isolated_home):
    assert config_module.get_matching_config().auto_accept_threshold == 0.8

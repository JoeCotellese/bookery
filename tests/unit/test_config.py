# ABOUTME: Tests for bookery config loader (library_root + env/file overrides).
# ABOUTME: Verifies default, env override, config file override, and persistence.

from pathlib import Path

import pytest

from bookery.core import config as config_module


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Redirect ~/.bookery to a temp directory and clear env overrides."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("BOOKERY_LIBRARY_ROOT", raising=False)
    yield tmp_path


def test_default_library_root_is_home_library(isolated_home):
    assert config_module.get_library_root() == isolated_home / ".library"


def test_default_creates_config_file_if_missing(isolated_home):
    config_module.get_library_root()
    assert (isolated_home / ".bookery" / "config.toml").exists()


def test_env_var_overrides_config_file(isolated_home, monkeypatch, tmp_path):
    override = tmp_path / "elsewhere"
    monkeypatch.setenv("BOOKERY_LIBRARY_ROOT", str(override))
    assert config_module.get_library_root() == override


def test_config_file_value_is_honored(isolated_home):
    config_dir = isolated_home / ".bookery"
    config_dir.mkdir()
    target = isolated_home / "custom-lib"
    (config_dir / "config.toml").write_text(f'library_root = "{target}"\n')

    assert config_module.get_library_root() == target


def test_env_var_beats_config_file(isolated_home, monkeypatch, tmp_path):
    config_dir = isolated_home / ".bookery"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        f'library_root = "{isolated_home / "from-file"}"\n'
    )
    env_target = tmp_path / "from-env"
    monkeypatch.setenv("BOOKERY_LIBRARY_ROOT", str(env_target))

    assert config_module.get_library_root() == env_target


def test_library_root_is_always_absolute(isolated_home):
    root = config_module.get_library_root()
    assert root.is_absolute()

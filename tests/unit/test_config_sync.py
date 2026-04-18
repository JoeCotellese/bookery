# ABOUTME: Unit tests for the [sync.kobo] section of bookery's TOML config.
# ABOUTME: Verifies defaults, overrides, and the get_sync_config() helper.

from pathlib import Path

import pytest

from bookery.core.config import get_sync_config, load_config


@pytest.fixture
def _isolated_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("BOOKERY_LIBRARY_ROOT", raising=False)
    return tmp_path


def test_defaults_when_no_sync_section(_isolated_home: Path) -> None:
    cfg = load_config()
    assert cfg.sync.kobo.books_subdir == "Books"
    assert cfg.sync.kobo.auto_detect is True


def test_sync_kobo_overrides_parsed(_isolated_home: Path) -> None:
    config_file = _isolated_home / ".bookery" / "config.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        "[sync.kobo]\n"
        'books_subdir = "MyBooks"\n'
        "auto_detect = false\n",
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.sync.kobo.books_subdir == "MyBooks"
    assert cfg.sync.kobo.auto_detect is False


def test_get_sync_config_shortcut(_isolated_home: Path) -> None:
    sync = get_sync_config()
    assert sync.kobo.books_subdir == "Books"

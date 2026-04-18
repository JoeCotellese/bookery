# ABOUTME: Unit tests for the [convert] section and data_dir extension of Config.

from pathlib import Path

import pytest

from bookery.core.config import ConvertConfig, get_convert_config, load_config


@pytest.fixture
def _isolated_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("BOOKERY_LIBRARY_ROOT", raising=False)
    return tmp_path


def test_defaults_when_no_convert_section(_isolated_home: Path) -> None:
    cfg = load_config()
    assert isinstance(cfg.convert, ConvertConfig)
    assert cfg.convert.llm_base_url == "http://localhost:1234/v1"
    assert cfg.convert.llm_model == "qwen2.5-7b-instruct"
    assert cfg.convert.llm_api_key == "lm-studio"
    assert cfg.convert.llm_max_retries == 3
    assert cfg.convert.prompt_version == 1
    assert cfg.convert.header_footer_threshold == 0.6


def test_data_dir_default(_isolated_home: Path) -> None:
    cfg = load_config()
    assert cfg.data_dir == _isolated_home / ".bookery" / "data"


def test_convert_overrides_parsed(_isolated_home: Path) -> None:
    config_file = _isolated_home / ".bookery" / "config.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        'library_root = "~/books"\n'
        "\n"
        "[convert]\n"
        'llm_base_url = "http://example:9999/v1"\n'
        'llm_model = "custom-model"\n'
        "llm_max_retries = 7\n"
        "prompt_version = 42\n"
        "header_footer_threshold = 0.8\n",
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.convert.llm_base_url == "http://example:9999/v1"
    assert cfg.convert.llm_model == "custom-model"
    assert cfg.convert.llm_max_retries == 7
    assert cfg.convert.prompt_version == 42
    assert cfg.convert.header_footer_threshold == 0.8
    # Unspecified key falls back to default.
    assert cfg.convert.llm_api_key == "lm-studio"


def test_get_convert_config_shortcut(_isolated_home: Path) -> None:
    cc = get_convert_config()
    assert isinstance(cc, ConvertConfig)
    assert cc.llm_model == "qwen2.5-7b-instruct"


def test_config_is_frozen(_isolated_home: Path) -> None:
    cfg = load_config()
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.convert.llm_model = "nope"  # type: ignore[misc]

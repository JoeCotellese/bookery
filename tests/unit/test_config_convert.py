# ABOUTME: Unit tests for the [convert.semantic] section and data_dir extension of Config.

from pathlib import Path

import pytest

from bookery.core.config import (
    ConvertConfig,
    SemanticConfig,
    get_convert_config,
    load_config,
)


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
    assert isinstance(cfg.convert.semantic, SemanticConfig)
    assert cfg.convert.semantic.provider == "lm-studio"
    assert cfg.convert.semantic.base_url == "http://localhost:1234/v1"
    assert cfg.convert.semantic.model == "qwen2.5-7b-instruct-1m"
    assert cfg.convert.semantic.api_key_env == ""
    assert cfg.convert.semantic.prompt_version == 1
    assert cfg.convert.semantic.llm_max_retries == 2


def test_data_dir_default(_isolated_home: Path) -> None:
    cfg = load_config()
    assert cfg.data_dir == _isolated_home / ".bookery" / "data"


def test_semantic_overrides_parsed(_isolated_home: Path) -> None:
    config_file = _isolated_home / ".bookery" / "config.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        'library_root = "~/books"\n'
        "\n"
        "[convert.semantic]\n"
        'provider = "openai"\n'
        'model = "gpt-5.4-nano"\n'
        'base_url = "https://api.openai.com/v1"\n'
        'api_key_env = "OPENAI_API_KEY"\n'
        "prompt_version = 42\n"
        "llm_max_retries = 5\n",
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.convert.semantic.provider == "openai"
    assert cfg.convert.semantic.model == "gpt-5.4-nano"
    assert cfg.convert.semantic.base_url == "https://api.openai.com/v1"
    assert cfg.convert.semantic.api_key_env == "OPENAI_API_KEY"
    assert cfg.convert.semantic.prompt_version == 42
    assert cfg.convert.semantic.llm_max_retries == 5


def test_resolve_api_key_from_env(
    _isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    cfg = SemanticConfig(api_key_env="OPENAI_API_KEY")
    assert cfg.resolve_api_key() == "sk-test-123"


def test_resolve_api_key_empty_env_name_returns_placeholder(
    _isolated_home: Path,
) -> None:
    # Empty api_key_env means local (LM Studio) — no real key needed.
    cfg = SemanticConfig(api_key_env="")
    assert cfg.resolve_api_key() == "lm-studio"


def test_resolve_api_key_missing_env_returns_empty(
    _isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NOT_SET_KEY", raising=False)
    cfg = SemanticConfig(api_key_env="NOT_SET_KEY")
    assert cfg.resolve_api_key() == ""


def test_get_convert_config_shortcut(_isolated_home: Path) -> None:
    cc = get_convert_config()
    assert isinstance(cc, ConvertConfig)
    assert cc.semantic.model == "qwen2.5-7b-instruct-1m"


def test_config_is_frozen(_isolated_home: Path) -> None:
    cfg = load_config()
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.convert.semantic.model = "nope"  # type: ignore[misc]

# ABOUTME: Loads persistent bookery configuration from ~/.bookery/config.toml.
# ABOUTME: Exposes library_root, convert options, and data_dir with env overrides and defaults.

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_DIR_NAME = ".bookery"
CONFIG_FILE_NAME = "config.toml"
DEFAULT_LIBRARY_DIR_NAME = ".library"
DEFAULT_DATA_DIR_NAME = "data"
ENV_LIBRARY_ROOT = "BOOKERY_LIBRARY_ROOT"

DEFAULT_LLM_BASE_URL = "http://localhost:1234/v1"
DEFAULT_LLM_MODEL = "qwen2.5-7b-instruct"
DEFAULT_LLM_API_KEY = "lm-studio"
DEFAULT_LLM_MAX_RETRIES = 3
DEFAULT_PROMPT_VERSION = 1
DEFAULT_HEADER_FOOTER_THRESHOLD = 0.6


@dataclass(frozen=True, slots=True)
class ConvertConfig:
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    llm_api_key: str = DEFAULT_LLM_API_KEY
    llm_max_retries: int = DEFAULT_LLM_MAX_RETRIES
    prompt_version: int = DEFAULT_PROMPT_VERSION
    header_footer_threshold: float = DEFAULT_HEADER_FOOTER_THRESHOLD


@dataclass(frozen=True)
class Config:
    library_root: Path
    data_dir: Path
    convert: ConvertConfig = field(default_factory=ConvertConfig)


def _config_path() -> Path:
    return Path.home() / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def _default_library_root() -> Path:
    return Path.home() / DEFAULT_LIBRARY_DIR_NAME


def _default_data_dir() -> Path:
    return Path.home() / CONFIG_DIR_NAME / DEFAULT_DATA_DIR_NAME


def _write_default_config(path: Path, library_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'library_root = "{library_root}"\n', encoding="utf-8")


def _parse_convert(section: dict[str, Any] | None) -> ConvertConfig:
    if not section:
        return ConvertConfig()
    return ConvertConfig(
        llm_base_url=str(section.get("llm_base_url", DEFAULT_LLM_BASE_URL)),
        llm_model=str(section.get("llm_model", DEFAULT_LLM_MODEL)),
        llm_api_key=str(section.get("llm_api_key", DEFAULT_LLM_API_KEY)),
        llm_max_retries=int(section.get("llm_max_retries", DEFAULT_LLM_MAX_RETRIES)),
        prompt_version=int(section.get("prompt_version", DEFAULT_PROMPT_VERSION)),
        header_footer_threshold=float(
            section.get("header_footer_threshold", DEFAULT_HEADER_FOOTER_THRESHOLD)
        ),
    )


def load_config() -> Config:
    """Load configuration from disk, creating a default file on first run.

    Precedence (highest wins):
      1. BOOKERY_LIBRARY_ROOT env var
      2. library_root in ~/.bookery/config.toml
      3. Default: ~/.library/
    """
    config_file = _config_path()
    data: dict[str, Any]
    if not config_file.exists():
        default = _default_library_root()
        _write_default_config(config_file, default)
        file_value: Path | None = default
        data = {}
    else:
        with config_file.open("rb") as f:
            data = tomllib.load(f)
        raw = data.get("library_root")
        file_value = Path(raw).expanduser() if raw else None

    env_value = os.environ.get(ENV_LIBRARY_ROOT)
    if env_value:
        library_root = Path(env_value).expanduser()
    elif file_value is not None:
        library_root = file_value
    else:
        library_root = _default_library_root()

    if not library_root.is_absolute():
        library_root = library_root.resolve()

    raw_data_dir = data.get("data_dir")
    data_dir = (
        Path(raw_data_dir).expanduser() if raw_data_dir else _default_data_dir()
    )
    if not data_dir.is_absolute():
        data_dir = data_dir.resolve()

    convert = _parse_convert(data.get("convert"))
    return Config(library_root=library_root, data_dir=data_dir, convert=convert)


def get_library_root() -> Path:
    """Return the configured library root as an absolute Path."""
    return load_config().library_root


def get_data_dir() -> Path:
    """Return the per-user data directory (caches, manifests) as an absolute Path."""
    return load_config().data_dir


def get_convert_config() -> ConvertConfig:
    """Return the [convert] configuration block."""
    return load_config().convert

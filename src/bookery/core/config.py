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

DEFAULT_PROVIDER = "lm-studio"
DEFAULT_MODEL = "qwen2.5-7b-instruct-1m"
DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_API_KEY_ENV = ""
DEFAULT_PROMPT_VERSION = 1
DEFAULT_LLM_MAX_RETRIES = 2
DEFAULT_MAX_TOKENS = 0  # 0 = don't send max_tokens; let the server decide


@dataclass(frozen=True, slots=True)
class SemanticConfig:
    provider: str = DEFAULT_PROVIDER          # "lm-studio" | "openai" | "anthropic"
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    api_key_env: str = DEFAULT_API_KEY_ENV    # env var name; "" for local
    prompt_version: int = DEFAULT_PROMPT_VERSION
    llm_max_retries: int = DEFAULT_LLM_MAX_RETRIES
    max_tokens: int = DEFAULT_MAX_TOKENS

    def resolve_api_key(self) -> str:
        """Resolve api_key_env to the actual key at use time. '' for local endpoints."""
        if not self.api_key_env:
            return "lm-studio"  # placeholder required by openai SDK; LM Studio ignores
        return os.environ.get(self.api_key_env, "")


@dataclass(frozen=True, slots=True)
class ConvertConfig:
    semantic: SemanticConfig = field(default_factory=SemanticConfig)


DEFAULT_KOBO_BOOKS_SUBDIR = "Bookery"
DEFAULT_KOBO_AUTO_DETECT = True


@dataclass(frozen=True, slots=True)
class SyncKoboConfig:
    books_subdir: str = DEFAULT_KOBO_BOOKS_SUBDIR
    auto_detect: bool = DEFAULT_KOBO_AUTO_DETECT


@dataclass(frozen=True, slots=True)
class SyncConfig:
    kobo: SyncKoboConfig = field(default_factory=SyncKoboConfig)


@dataclass(frozen=True)
class Config:
    library_root: Path
    data_dir: Path
    convert: ConvertConfig = field(default_factory=ConvertConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)


def _config_path() -> Path:
    return Path.home() / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def _default_library_root() -> Path:
    return Path.home() / DEFAULT_LIBRARY_DIR_NAME


def _default_data_dir() -> Path:
    return Path.home() / CONFIG_DIR_NAME / DEFAULT_DATA_DIR_NAME


def _write_default_config(path: Path, library_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'library_root = "{library_root}"\n', encoding="utf-8")


def _parse_semantic(section: dict[str, Any] | None) -> SemanticConfig:
    if not section:
        return SemanticConfig()
    return SemanticConfig(
        provider=str(section.get("provider", DEFAULT_PROVIDER)),
        model=str(section.get("model", DEFAULT_MODEL)),
        base_url=str(section.get("base_url", DEFAULT_BASE_URL)),
        api_key_env=str(section.get("api_key_env", DEFAULT_API_KEY_ENV)),
        prompt_version=int(section.get("prompt_version", DEFAULT_PROMPT_VERSION)),
        llm_max_retries=int(section.get("llm_max_retries", DEFAULT_LLM_MAX_RETRIES)),
        max_tokens=int(section.get("max_tokens", DEFAULT_MAX_TOKENS)),
    )


def _parse_convert(section: dict[str, Any] | None) -> ConvertConfig:
    if not section:
        return ConvertConfig()
    return ConvertConfig(semantic=_parse_semantic(section.get("semantic")))


def _parse_sync_kobo(section: dict[str, Any] | None) -> SyncKoboConfig:
    if not section:
        return SyncKoboConfig()
    return SyncKoboConfig(
        books_subdir=str(section.get("books_subdir", DEFAULT_KOBO_BOOKS_SUBDIR)),
        auto_detect=bool(section.get("auto_detect", DEFAULT_KOBO_AUTO_DETECT)),
    )


def _parse_sync(section: dict[str, Any] | None) -> SyncConfig:
    if not section:
        return SyncConfig()
    return SyncConfig(kobo=_parse_sync_kobo(section.get("kobo")))


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
    sync = _parse_sync(data.get("sync"))
    return Config(
        library_root=library_root, data_dir=data_dir, convert=convert, sync=sync
    )


def get_library_root() -> Path:
    """Return the configured library root as an absolute Path."""
    return load_config().library_root


def get_data_dir() -> Path:
    """Return the per-user data directory (caches, manifests) as an absolute Path."""
    return load_config().data_dir


def get_convert_config() -> ConvertConfig:
    """Return the [convert] configuration block."""
    return load_config().convert


def get_sync_config() -> SyncConfig:
    """Return the [sync] configuration block."""
    return load_config().sync

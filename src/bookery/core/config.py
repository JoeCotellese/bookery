# ABOUTME: Loads persistent bookery configuration from ~/.bookery/config.toml.
# ABOUTME: Exposes library_root with env override (BOOKERY_LIBRARY_ROOT) and defaults.

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR_NAME = ".bookery"
CONFIG_FILE_NAME = "config.toml"
DEFAULT_LIBRARY_DIR_NAME = ".library"
ENV_LIBRARY_ROOT = "BOOKERY_LIBRARY_ROOT"


@dataclass(frozen=True)
class Config:
    library_root: Path


def _config_path() -> Path:
    return Path.home() / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def _default_library_root() -> Path:
    return Path.home() / DEFAULT_LIBRARY_DIR_NAME


def _write_default_config(path: Path, library_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'library_root = "{library_root}"\n', encoding="utf-8")


def load_config() -> Config:
    """Load configuration from disk, creating a default file on first run.

    Precedence (highest wins):
      1. BOOKERY_LIBRARY_ROOT env var
      2. library_root in ~/.bookery/config.toml
      3. Default: ~/.library/
    """
    config_file = _config_path()
    if not config_file.exists():
        default = _default_library_root()
        _write_default_config(config_file, default)
        file_value: Path | None = default
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
    return Config(library_root=library_root)


def get_library_root() -> Path:
    """Return the configured library root as an absolute Path."""
    return load_config().library_root

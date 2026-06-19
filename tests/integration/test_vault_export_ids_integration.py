# ABOUTME: Integration tests for vault-export's --random-ids flag and --uuid alias.
# ABOUTME: Exercises the full CLI surface through to EpubMetadata without invoking pandoc.

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from bookery.cli import cli
from bookery.cli.deprecation import reset_deprecation_state
from bookery.core.config import Config, VaultExportConfig
from bookery.core.vault.epub import stable_uuid


@pytest.fixture
def vault_with_note(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "n.md").write_text("# n\n\nbody\n", encoding="utf-8")
    return vault


@pytest.fixture
def patched_render(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _render(markdown, assets, metadata, output_path) -> None:
        captured["metadata"] = metadata
        Path(output_path).write_bytes(b"fake-epub")

    monkeypatch.setattr(
        "bookery.cli.commands.vault_export_cmd.render_epub",
        _render,
    )
    monkeypatch.setattr(
        "bookery.cli.commands.vault_export_cmd.load_config",
        lambda: Config(
            library_root=Path("/tmp/_lib"),
            data_dir=Path("/tmp/_data"),
            vault_export=VaultExportConfig(),
        ),
    )
    return captured


def test_random_ids_and_old_alias_route_to_same_branch(
    vault_with_note: Path,
    patched_render: dict[str, Any],
    tmp_path: Path,
) -> None:
    """`--random-ids` and `--uuid random` must both produce a non-stable
    identifier — proves the alias is fully wired into the boolean path.
    """
    runner = CliRunner()

    reset_deprecation_state()
    out_new = tmp_path / "new.epub"
    runner.invoke(
        cli,
        ["vault-export", "--vault", str(vault_with_note), "-o", str(out_new), "--random-ids"],
        catch_exceptions=False,
    )
    id_new = patched_render["metadata"].identifier

    reset_deprecation_state()
    out_old = tmp_path / "old.epub"
    runner.invoke(
        cli,
        ["vault-export", "--vault", str(vault_with_note), "-o", str(out_old), "--uuid", "random"],
        catch_exceptions=False,
    )
    id_old = patched_render["metadata"].identifier

    stable = stable_uuid(vault_with_note)
    assert id_new != stable
    assert id_old != stable
    # Both random; not equal to each other either (random_uuid is uuid4).
    assert id_new != id_old


def test_uuid_stable_alias_matches_default_behavior(
    vault_with_note: Path,
    patched_render: dict[str, Any],
    tmp_path: Path,
) -> None:
    """`--uuid stable` should produce the same identifier as no flag at all."""
    runner = CliRunner()

    reset_deprecation_state()
    out_default = tmp_path / "default.epub"
    runner.invoke(
        cli,
        ["vault-export", "--vault", str(vault_with_note), "-o", str(out_default)],
        catch_exceptions=False,
    )
    id_default = patched_render["metadata"].identifier

    reset_deprecation_state()
    out_alias = tmp_path / "alias.epub"
    runner.invoke(
        cli,
        [
            "vault-export",
            "--vault",
            str(vault_with_note),
            "-o",
            str(out_alias),
            "--uuid",
            "stable",
        ],
        catch_exceptions=False,
    )
    id_alias = patched_render["metadata"].identifier

    assert id_default == id_alias == stable_uuid(vault_with_note)

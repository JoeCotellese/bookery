# ABOUTME: Unit tests for the vault-export CLI's `--random-ids` flag and `--uuid` alias.
# ABOUTME: Mocks pandoc so the flag wiring can be tested without a real EPUB render.

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from bookery.cli import cli
from bookery.cli.deprecation import reset_deprecation_state


@pytest.fixture
def fake_vault(tmp_path: Path) -> Path:
    """A minimal vault with one markdown note so walk_vault produces output."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Note\n\nbody\n", encoding="utf-8")
    return vault


@pytest.fixture
def stub_render(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture the EpubMetadata passed to render_epub without invoking pandoc.

    Also stubs load_config so the developer's real ~/.bookery/config.toml
    (which may set vault_path, folders, etc.) does not leak into the test.
    """
    captured: dict[str, Any] = {}

    def _fake_render(
        markdown: str,
        assets: list[Path],
        metadata: Any,
        output_path: Path,
    ) -> None:
        captured["metadata"] = metadata
        captured["output_path"] = output_path
        output_path.write_bytes(b"not-a-real-epub")

    monkeypatch.setattr(
        "bookery.cli.commands.vault_export_cmd.render_epub",
        _fake_render,
    )

    from bookery.core.config import Config, VaultExportConfig

    def _fake_load_config() -> Config:
        return Config(
            library_root=Path("/tmp/bookery-lib"),
            data_dir=Path("/tmp/bookery-data"),
            vault_export=VaultExportConfig(),
        )

    monkeypatch.setattr(
        "bookery.cli.commands.vault_export_cmd.load_config",
        _fake_load_config,
    )
    return captured


def test_default_uses_stable_identifier(
    fake_vault: Path, stub_render: dict[str, Any], tmp_path: Path,
) -> None:
    reset_deprecation_state()
    runner = CliRunner()
    out = tmp_path / "out.epub"
    result = runner.invoke(
        cli,
        ["vault-export", "--vault", str(fake_vault), "-o", str(out)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    # Stable UUIDs are deterministic and derived from the vault path.
    from bookery.core.vault.epub import stable_uuid
    assert stub_render["metadata"].identifier == stable_uuid(fake_vault)
    assert result.stderr == ""


def test_random_ids_flag_produces_random_identifier(
    fake_vault: Path, stub_render: dict[str, Any], tmp_path: Path,
) -> None:
    reset_deprecation_state()
    runner = CliRunner()
    out = tmp_path / "out.epub"
    result = runner.invoke(
        cli,
        ["vault-export", "--vault", str(fake_vault), "-o", str(out), "--random-ids"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    from bookery.core.vault.epub import stable_uuid
    identifier = stub_render["metadata"].identifier
    assert identifier.startswith("urn:uuid:")
    assert identifier != stable_uuid(fake_vault)
    # --random-ids is the canonical surface; no deprecation warning expected.
    assert result.stderr == ""


def test_deprecated_uuid_random_translates_to_random_ids(
    fake_vault: Path, stub_render: dict[str, Any], tmp_path: Path,
) -> None:
    reset_deprecation_state()
    runner = CliRunner()
    out = tmp_path / "out.epub"
    result = runner.invoke(
        cli,
        ["vault-export", "--vault", str(fake_vault), "-o", str(out), "--uuid", "random"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    from bookery.core.vault.epub import stable_uuid
    identifier = stub_render["metadata"].identifier
    assert identifier.startswith("urn:uuid:")
    assert identifier != stable_uuid(fake_vault)
    assert (
        "warning: '--uuid' is deprecated; use '--random-ids' instead."
        in result.stderr
    )


def test_deprecated_uuid_stable_keeps_stable_identifier(
    fake_vault: Path, stub_render: dict[str, Any], tmp_path: Path,
) -> None:
    reset_deprecation_state()
    runner = CliRunner()
    out = tmp_path / "out.epub"
    result = runner.invoke(
        cli,
        ["vault-export", "--vault", str(fake_vault), "-o", str(out), "--uuid", "stable"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    from bookery.core.vault.epub import stable_uuid
    assert stub_render["metadata"].identifier == stable_uuid(fake_vault)
    assert "warning: '--uuid' is deprecated" in result.stderr


def test_uuid_invalid_value_errors(
    fake_vault: Path, stub_render: dict[str, Any], tmp_path: Path,
) -> None:
    reset_deprecation_state()
    runner = CliRunner()
    out = tmp_path / "out.epub"
    result = runner.invoke(
        cli,
        ["vault-export", "--vault", str(fake_vault), "-o", str(out), "--uuid", "bogus"],
    )
    assert result.exit_code != 0
    # Click's choice-validation surfaces the invalid value in its error text.
    combined = (result.output or "") + (result.stderr or "")
    assert "bogus" in combined


def test_deprecation_warning_fires_once(
    fake_vault: Path, stub_render: dict[str, Any], tmp_path: Path,
) -> None:
    reset_deprecation_state()
    runner = CliRunner()
    out = tmp_path / "out.epub"
    result = runner.invoke(
        cli,
        ["vault-export", "--vault", str(fake_vault), "-o", str(out), "--uuid", "random"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert result.stderr.count("warning: '--uuid' is deprecated") == 1


def test_config_uuid_mode_random_still_honored_without_flag(
    fake_vault: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`uuid_mode = "random"` in config still drives the identifier when no
    flag is passed. Config-level deprecation is out of scope for this change.
    """
    reset_deprecation_state()
    captured: dict[str, Any] = {}

    def _fake_render(
        markdown: str,
        assets: list[Path],
        metadata: Any,
        output_path: Path,
    ) -> None:
        captured["metadata"] = metadata
        output_path.write_bytes(b"not-a-real-epub")

    monkeypatch.setattr(
        "bookery.cli.commands.vault_export_cmd.render_epub",
        _fake_render,
    )

    from bookery.core.config import Config, VaultExportConfig

    def _fake_load_config() -> Config:
        return Config(
            library_root=Path("/tmp/bookery-lib"),
            data_dir=Path("/tmp/bookery-data"),
            vault_export=VaultExportConfig(uuid_mode="random"),
        )

    monkeypatch.setattr(
        "bookery.cli.commands.vault_export_cmd.load_config",
        _fake_load_config,
    )

    runner = CliRunner()
    out = tmp_path / "out.epub"
    result = runner.invoke(
        cli,
        ["vault-export", "--vault", str(fake_vault), "-o", str(out)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    from bookery.core.vault.epub import stable_uuid
    identifier = captured["metadata"].identifier
    assert identifier.startswith("urn:uuid:")
    assert identifier != stable_uuid(fake_vault)

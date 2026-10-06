# ABOUTME: Acceptance test for #316: Bookery builds and publishes to PyPI as bookery-cli.
# ABOUTME: Builds the real wheel, installs it in a clean venv, checks metadata, workflow, README.

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"
README = ROOT / "README.md"


def _project() -> dict:
    return tomllib.loads(PYPROJECT.read_text())["project"]


@pytest.fixture(scope="module")
def installed_wheel(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Build the wheel with uv and install it into an isolated venv."""
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1, wheels
    venv = tmp_path_factory.mktemp("venv")
    subprocess.run(["uv", "venv", str(venv)], check=True, capture_output=True)
    subprocess.run(
        ["uv", "pip", "install", "--python", str(venv / "bin" / "python"), str(wheels[0])],
        check=True,
        capture_output=True,
    )
    return wheels[0], venv


def test_ac1_wheel_is_named_bookery_cli(installed_wheel: tuple[Path, Path]) -> None:
    wheel, _ = installed_wheel
    assert wheel.name == f"bookery_cli-{_project()['version']}-py3-none-any.whl"


def test_ac2_installed_command_reports_version(installed_wheel: tuple[Path, Path]) -> None:
    _, venv = installed_wheel
    result = subprocess.run(
        [str(venv / "bin" / "bookery"), "--version"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert _project()["version"] in result.stdout


def test_ac3_installed_wheel_ships_web_assets(installed_wheel: tuple[Path, Path]) -> None:
    _, venv = installed_wheel
    check = (
        "import importlib.resources as r; w = r.files('bookery.web'); "
        "assert w.joinpath('templates').is_dir(); assert w.joinpath('static').is_dir()"
    )
    result = subprocess.run(
        [str(venv / "bin" / "python"), "-I", "-c", check], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_ac4_pyproject_metadata() -> None:
    project = _project()
    assert project["name"] == "bookery-cli"
    assert {"Homepage", "Repository", "Issues"} <= set(project["urls"])
    assert {"ebook", "epub", "kobo", "calibre"} <= set(project["keywords"])
    classifiers = project["classifiers"]
    # PEP 639: PyPI rejects uploads carrying both License-Expression and a License classifier
    assert project["license"] == "MIT"
    assert not any(c.startswith("License ::") for c in classifiers)
    assert "Programming Language :: Python :: 3.12" in classifiers
    assert "Environment :: Console" in classifiers
    assert "Environment :: Web Environment" in classifiers
    assert "kobo" in project["description"].lower()


def test_ac5_publish_workflow_uses_trusted_publishing() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    triggers = workflow.get("on", workflow.get(True))  # PyYAML parses bare `on` as True
    assert triggers["push"]["tags"], "publish must trigger on version tags"
    text = WORKFLOW.read_text()
    assert "id-token: write" in text
    assert "uv build" in text
    assert "uv publish" in text
    assert "--version" in text, "workflow must smoke-test the built wheel"
    assert "bookery.web" in text, "workflow must check web assets in the built wheel"
    assert "secrets." not in text, "trusted publishing needs no stored secrets"


def test_ac6_publish_workflow_passes_actionlint() -> None:
    assert shutil.which("uvx"), "uvx is required to run actionlint"
    result = subprocess.run(
        ["uvx", "--from", "actionlint-py", "actionlint", str(WORKFLOW)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_ac7_readme_install_instructions() -> None:
    readme = README.read_text()
    assert "uv tool install bookery-cli" in readme
    assert "pipx install bookery-cli" in readme
    assert "uv tool upgrade bookery-cli" in readme
    assert "uv tool uninstall bookery-cli" in readme
    assert "uv tool install git+https://github.com/joecotellese/bookery.git" in readme

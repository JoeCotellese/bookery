# DoD results: #316 Publish to PyPI as bookery-cli

1. Date: 2026-10-06 08:35 EDT
2. Issue: #316
3. Branch: feature/316-pypi-bookery-cli
4. Commit verified: 9d1f799
5. Status: PASS-with-caveats
6. Domain: python

## Unit suite

7. `uv run pytest`: 2753 passed, 0 failed. The only output is the known `imghdr` DeprecationWarning from the third-party `mobi` package (`mobi/mobi_cover.py:4`). It also appears on `main` and has nothing to do with this change.
8. Regression sweep: `tests/e2e/test_cli.py::TestCliVersion::test_version` passed, so `bookery.__version__` resolves under the new distribution name.
9. `uv run ruff check src/ tests/`: all checks passed. `uv run pyright src/`: 0 errors.

## Acceptance criteria

10. AC1: the wheel is named `bookery_cli-2026.8.1-py3-none-any.whl`. Channel: `test_ac1_wheel_is_named_bookery_cli`. PASSED.
11. AC2: the wheel, installed in a fresh venv, provides `bookery`, and `bookery --version` prints `2026.8.1`. Channel: `test_ac2_installed_command_reports_version`. PASSED. Before the version lookups were fixed, this test failed (step 2g of the plan), so it guards the fix.
12. AC3: the installed wheel ships `bookery/web/templates` and `bookery/web/static`. Channel: `test_ac3_installed_wheel_ships_web_assets`. PASSED.
13. AC4: `pyproject.toml` has the name, URLs, keywords, classifiers, the SPDX `license = "MIT"` with no `License ::` classifier, and Kobo in the description. Channel: `test_ac4_pyproject_metadata`. PASSED. The test was amended (see item 19).
14. AC5: `publish.yml` triggers on CalVer tags, builds with `uv build`, smoke-tests `--version` and `bookery.web`, and publishes with `uv publish` under `id-token: write` with no secrets. Channel: `test_ac5_publish_workflow_uses_trusted_publishing`. PASSED. Both smoke commands were also run locally against a fresh `uv build` and passed.
15. AC6: the workflow passes actionlint. Channel: `test_ac6_publish_workflow_passes_actionlint`. PASSED.
16. AC7: the README shows `uv tool install bookery-cli` and `pipx install bookery-cli`, upgrade and uninstall use `bookery-cli`, and the git+https install remains. Channel: `test_ac7_readme_install_instructions`. PASSED.
17. AC8 [manual]: the release is visible on pypi.org and a clean `uv tool install bookery-cli` works. Accepted on its proxy (AC1, AC2, AC3, AC5, AC6 all passed) by the maintainer on 2026-10-06. The real check is owed after merge: register the pending Trusted Publisher, then push the first tag.

## Reconciliation

18. 8 criteria in the issue: 7 `[test:]`, each observed by its named test, and 1 `[manual]`, answered on its proxy. 8 of 8 accounted for.

## Findings

19. AC4 originally required a `License ::` classifier. PEP 639 requires PyPI to reject uploads that carry both `License-Expression` (which uv_build emits from `license = "MIT"`) and a license classifier, so the first upload would have failed. With the maintainer's approval at /implement, the test and the issue's AC4 were amended in commit cfc7928. A /retro on the /ready gate is owed: it validated the metadata against the AC, not against PyPI's upload rules.
20. Out of scope, filed as #317: the first `bookery` run after a fresh install prints luqum/ply "Generating LALR tables" warnings to stderr.

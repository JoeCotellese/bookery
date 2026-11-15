# DoD results: #326 vault-export stale catalog hash

1. Date: 2026-11-15
2. Issue: #326
3. Branch: fix/326-vault-export-stale-hash
4. Commit: 1629275
5. Status: PASS-with-caveats

## Unit suite

1. `uv run pytest -q -p no:randomly`: 2774 passed, 0 failed.
2. Caveat: 1 DeprecationWarning (`imghdr`) from third-party `mobi/mobi_cover.py:4`. Present on main before this branch; not caused by this change.

## Criteria

1. AC1 `[test: test_ac1_reexport_refreshes_existing_row_hash]`: PASS
   1a. Evidence: `tests/e2e/test_vault_export_rehash_326.py` PASSED. Asserts one row, same id, file_hash equals SHA-256 of the re-exported EPUB, date_modified later than backdated value, output says updated and not skipped.
   1b. Mutation check: restoring `vault_export_cmd.py` from f1e3302 (pre-fix) makes the test fail (1 failed).

## Regression sweep

1. `tests/e2e/test_vault_export_cli.py`: included in the full suite, green.

Reconciliation: 1 criterion in issue, 1 observed, 1 passing.

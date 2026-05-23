# [plan-05] Catalog Path Truth & Hygiene — explicit match signal, canonical paths, prune, test isolation

## Defect

`output_path` is overloaded: it means both "this book has a managed library location" *and* "this book has been matched against a metadata provider." After the library-canonical migration every row has `output_path` populated, so the second meaning silently broke — the web checkmark, `rematch --resume`, and any caller using `output_path IS NOT NULL` as a matched-flag now give wrong answers. In parallel, the import pipeline still leaves `output_path` NULL for unmatched books, the catalog has no way to detect or remove stale rows whose files were deleted, and tests routinely write to the real `~/.bookery/library.db` because they don't pass `--db` or honor `BOOKERY_LIBRARY_ROOT`. All four are the same root defect: the catalog has never had a clear path-truth invariant or hygiene story.

## Children

- #64 — separate "matched" from "in library" (output_path overloaded)
- #59 — import pipeline should record output_path for unmatched books
- #101 — add `bookery prune` to remove catalog rows whose files are missing
- #74 — catalog hygiene: detect and prune stale book entries
- #77 — pytest runs pollute real user catalog with tmp paths

## Fix sequence

1. **Schema migration: explicit match signal.** Add `metadata_matched_at TEXT` column to `books`. Match pipeline writes the timestamp on accepted match. Backfill: rows whose `identifiers` JSON contains a provider id get a backfilled timestamp; the rest stay NULL.
2. **Switch every call site to the new signal.** `web/templates/_table.html` checkmark, `cli/commands/rematch_cmd.py --resume`, `cli/commands/info_cmd.py` display, anywhere else that grepped `output_path IS NOT NULL` for matched intent.
3. **Importer always sets `output_path`.** For unmatched imports, set `output_path = source_path.parent / source_path.name` after the library-canonical copy. Decision recorded in the issue: matched and unmatched rows both have a real on-disk pointer. No backfill of pre-existing rows (call out in release notes).
4. **`bookery prune` command.** Walks catalog. For each row, checks `source_path` and `output_path`. Default `--dry-run`; `-y/--yes` deletes; `--check source|output|both` (default `both`). FK cascade handles `book_genres`, `book_tags`, `book_field_provenance`. Distinguishes "source missing but output present" (warn + offer rewrite) from "both missing" (orphan).
5. **Test-isolation guardrail.** Add a session-scoped pytest fixture that fails any test attempting to open the default `~/.bookery/library.db` or write under `~/.bookery/library/`. Conftest enforces `BOOKERY_LIBRARY_ROOT=$tmp_path` + `--db $tmp_path/library.db` for every test in `tests/e2e/` and `tests/integration/`. One-time cleanup query for already-polluted catalogs documented in the README.

## Test matrix

| Axis A (row state) | Axis B (operation) | Required behavior |
|---|---|---|
| matched | `--resume` | skipped |
| unmatched | `--resume` | reprocessed |
| matched, web list | render | checkmark shown |
| unmatched, web list | render | no checkmark |
| import without `--match` | catalog | `output_path` populated to canonical path |
| import with `--match` accept | catalog | `output_path` + `metadata_matched_at` both set |
| source missing, output present | `prune --check both` | warn, do not delete; offer rewrite via separate flag |
| both missing | `prune --check both -y` | row deleted, FK cascades succeed |
| `prune` default | invocation | dry-run table; no DB mutation |
| any test in `tests/e2e` | runtime | fails fast if it touches `~/.bookery/` |

The matrix lives in `tests/integration/test_catalog_path_truth.py` and a new `tests/conftest.py` guard, both run in CI.

## Out of scope

- Filesystem reverse-discovery (rebuilding the catalog from a `library_root` walk).
- Auto-prune at sync time. Sync stays read-only against the catalog.
- Refusing to prune rows with user-applied metadata without `--force` (file as follow-up if it bites).
- Reading-progress and stats reporting (separate work — `bookery stats`).

# [plan-09] Kobo Sync Lifecycle — additive-by-default, prune what we wrote, survive legacy encodings

## Defect

`bookery sync kobo` is purely additive — books removed from the local catalog leave orphaned `.kepub.epub` files on the device — and it dies on any EPUB whose OPF declares a non-UTF-8 encoding because the upstream kepubify Go decoder has no `CharsetReader`. The lifecycle is incomplete (no way to bring the device back into sync without manual file deletion) and brittle (one bad OPF aborts the book). Both come from the same defect: sync has no end-to-end lifecycle owner — it only ever writes.

## Children

- #73 — `--prune` flag to remove device files we wrote
- #78 — sync fails on EPUBs with iso-8859-1 encoded OPF (kepubify upstream)

## Fix sequence

1. **Preflight OPF normalization (#78).** In the sync workspace, before handing the EPUB to kepubify, detect a non-UTF-8 XML declaration in `content.opf`, decode via `golang.org/x/text/encoding/charmap`-equivalent (or Python's `codecs`), and rewrite to UTF-8 in the temp copy. The library original is never touched (non-destructive contract). Falls back to skip + warn if normalization itself fails. File upstream issue at `pgaskin/kepubify` suggesting a `CharsetReader` so the workaround can eventually retire.
2. **Precise prune (#73).** `bookery sync kobo --prune` walks `KepubCache.iter_entries()`, takes the set difference against `books.file_hash` for the current catalog, and deletes only those `device_path` entries whose `source_hash` no longer corresponds to a catalog book. Cache row is removed after a successful delete. Empty parent dirs under `<kobo>/<books_subdir>/` removed best-effort. Files not in the cache are never touched — including manual sideloads under the same subdir.
3. **`--prune --dry-run`** prints the planned deletes and changes nothing.
4. **Reconcile orphaned cache rows.** Cache rows whose `device_path` no longer exists on the device (user manually deleted) are tidied up during prune.

## Test matrix

| Axis A (device state) | Axis B (catalog state) | Flag | Required behavior |
|---|---|---|---|
| `book.kepub.epub` written by bookery | book removed from catalog | `--prune` | file deleted, cache row removed |
| same | same | `--prune --dry-run` | print plan only, no change |
| manual sideload in `<kobo>/<subdir>/` | not in cache | `--prune` | untouched |
| cache row points at deleted device file | n/a | `--prune` | cache row tidied, no error |
| EPUB with iso-8859-1 OPF | present | default sync | OPF normalized in workspace, kepubify succeeds, original untouched |
| EPUB with unrecognized encoding | present | default sync | skip + warn, sync continues |
| any EPUB | present | default sync | library original byte-identical after run |

The matrix lives in `tests/integration/test_kobo_sync_lifecycle.py` and runs in CI.

## Out of scope

- Two-way sync (importing reading progress / annotations from the device).
- Pruning by anything other than catalog membership (tag filters, format filters).
- Deleting the entire `<kobo>/<books_subdir>/` subtree as a "nuke" command.
- Migrating away from kepubify upstream.

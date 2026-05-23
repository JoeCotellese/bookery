# [plan-08] Import Dedup & Format Equivalence — importer recognizes the same book in different shapes

## Defect

The import pipeline treats every file as a distinct book. It does not know that `book.epub` and `book.mobi` in the same directory are the same Calibre item, that two files with the same ISBN are duplicates, or that title+author identifies the same work across directories. Bookery also can't yet read MOBI metadata or convert MOBI → EPUB, which means the 58% of the test Calibre library that is MOBI-only is invisible to dedup decisions. The root defect is that import has no model of equivalence — neither format equivalence (one Calibre dir = one book) nor identity equivalence (ISBN / normalized title+author).

## Children

- #36 — skip MOBI conversion when EPUB exists in same directory
- #37 — metadata-based duplicate detection (ISBN + title+author)
- #6 — research: MOBI metadata extraction and MOBI → EPUB conversion

## Fix sequence

1. **Format equivalence first (#36).** New `src/bookery/core/dedup.py` with `filter_redundant_mobis(mobi_files, epub_files) -> (to_convert, skipped)`. Group by parent dir. If any EPUB exists in a MOBI's dir, skip the MOBI. Reported in the conversion summary (`"N skipped — EPUB exists in directory"`). Edges: multiple EPUBs in dir, mismatched filenames (still skip — Calibre convention).
2. **Normalization helpers (#37 / Story 1).** In the same `dedup.py`: `normalize_for_dedup(title)`, `normalize_author_for_dedup(author)`, `normalize_isbn(isbn)` (strip hyphens, ISBN-10 → ISBN-13).
3. **`find_duplicate` on the catalog.** New `DuplicateMatch(record, reason)`; `LibraryCatalog.find_duplicate(metadata) -> DuplicateMatch | None`. ISBN match wins; falls through to title+author when one side has no ISBN.
4. **Importer wiring.** `ImportResult` grows `skipped_hash`, `skipped_metadata`, `forced`, `skip_details` (with a `SkipDetail` dataclass). `import_books()` takes a `force_duplicates: bool`. `bookery import --force-duplicates` flag added; default behavior skips with reason; summary breaks down by skip type.
5. **MOBI research (#6) as input to step 1's edges.** Document recommended library for MOBI metadata reading and MOBI → EPUB conversion, success-rate expectations on the test library, DRM detection/skip behavior. The research output decides whether a future MOBI handler joins this plan or spins off as its own plan.

## Test matrix

| Axis A (input shape) | Axis B (flag) | Required behavior |
|---|---|---|
| dir has `book.epub` + `book.mobi` | `--convert` | MOBI skipped, EPUB imported, summary shows skip |
| dir has only `book.mobi` | `--convert` | MOBI converts and imports |
| dir has multiple EPUBs + 1 MOBI | `--convert` | MOBI skipped |
| dir has `book.mobi` + `other.epub` (mismatched names) | `--convert` | MOBI still skipped (Calibre convention) |
| catalog has ISBN X; import file with same ISBN | default | skipped (`reason="isbn"`) |
| ISBN-10 vs ISBN-13 of same book | default | recognized as duplicate via normalization |
| only one side has ISBN | default | falls through to title+author |
| catalog has "Name of the Rose" / "Eco, Umberto" | default | duplicate skipped on case/whitespace/article variants |
| same as above | `--force-duplicates` | imported anyway with warning |
| import summary | any | counts of `skipped_hash`, `skipped_metadata`, `forced` printed |

The matrix lives in `tests/integration/test_import_dedup.py` and runs in CI.

## Out of scope

- Implementing the MOBI handler (decision deferred until research lands).
- Cross-format equivalence beyond co-directory MOBI/EPUB (e.g. matching a MOBI in one dir to an EPUB in another by normalized identity) — possible once MOBI metadata is readable; track separately.
- AZW3, PDF, TXT handler work — file follow-up plans only if the research justifies it.
- Reverse-dedup UI in the web app.

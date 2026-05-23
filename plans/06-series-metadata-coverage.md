# [plan-06] Series Metadata Coverage — providers + heuristic fallback for series name and position

## Defect

Neither current provider gives reliable series data: Open Library has a free-text series name but rarely a position; Google Books exposes structured `seriesInfo` but only for Play-sold volumes and we don't parse it; nothing handles older mass-market paperbacks where the *title itself* encodes series membership. As a result `BookMetadata.series` and `series_index` are mostly NULL across the catalog. The root defect is that the series story was never built end-to-end across the provider stack with a defined heuristic fallback.

## Children

- #98 — add Hardcover provider for series, ratings, and user tags
- #96 — parse Google Books `seriesInfo` for name + numeric position
- #99 — heuristic series inference from title patterns and author clustering

## Fix sequence

1. **Google Books `seriesInfo` parser.** `_parse_volume` reads both API shapes: `volumeSeries[].seriesId` → `identifiers["googlebooks_series"]`; `volumeSeries[].orderNumber` and `seriesInfo.bookDisplayNumber` → `BookMetadata.series_index`. Cheapest win and exercises the consensus merge.
2. **Hardcover provider.** `HardcoverProvider` implements `MetadataProvider` against `POST https://api.hardcover.app/v1/graphql`. API token from `HARDCOVER_API_KEY` env var only — never in `config.toml`. Queries by ISBN (primary), title/author (fallback). Maps `featured_series.series.name` → `series`, `featured_series.position` → `series_index`, plus `rating`, `ratings_count`, tags → `subjects`. Registered in `build_metadata_provider`. Uses existing `CachingHttpClient`.
3. **Title-pattern heuristic fallback.** Regex extractor for the common patterns:
   - `Name (Series #N)`, `Name (Series, Book N)`, `Name, Book N`
   - `Name: A Series Novel`, `Name: A Series Mystery`
   - `Series: Name` (colon-separated)
   Returns `(series_name, position|None)` or `None`. Only fires when `BookMetadata.series` is still NULL after provider consensus. Provenance stamped `source="heuristic"` so users can see (and override) inferred values. Respects user locks.
4. **`bookery series infer` CLI** — `<id>` dry-runs extraction, `--all` batch-fills across catalog. `--author "Steve Berry"` clusters subtitle tokens (v2 / optional within this plan).
5. **Consensus priority.** OL → GB → Hardcover, with Hardcover highest trust for `series`, `series_index`, `rating` once per-field priority lands (or document the override stack now).

## Test matrix

| Axis A (book) | Axis B (provider stack) | Required behavior |
|---|---|---|
| Play-sold volume, has `seriesInfo` | GB only | `series_index` populated; `googlebooks_series` id stashed |
| Pre-`seriesInfo` API shape | GB only | `bookDisplayNumber` parsed into `series_index` |
| ISBN-known, in Hardcover | Hardcover | `series`, `series_index`, `rating`, `ratings_count` populated |
| No ISBN, title/author known | Hardcover fallback | series fields populated when match confidence ≥ threshold |
| `"Foo (Series #3)"` title | heuristic only | `series="Series"`, `series_index=3`, provenance `heuristic` |
| `"Foo: A Bar Novel"` title | heuristic only | `series="Bar"`, no position, provenance `heuristic` |
| Provider returns series | heuristic | does NOT overwrite provider value |
| User-locked series field | any path | never overwritten |
| Hardcover rate limit | bulk rematch | backoff / surface error cleanly |

The matrix lives in `tests/metadata/test_series_coverage.py` (unit) + an opt-in integration marker for live providers; both gates pass CI.

## Out of scope

- Per-field priority configurability inside `ConsensusProvider` beyond the documented stack.
- Fuzzy matching against online series databases (Hardcover already covers this).
- Series-level pages in the web UI.
- Author clustering at scale (v2 within #99 — keep narrow if it bloats the plan).

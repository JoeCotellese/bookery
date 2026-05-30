# Bookery Roadmap

## Phase 1: Scaffold + EPUB Metadata Read/Write
- [x] Project scaffold (uv, pyproject.toml, directory structure)
- [x] `BookMetadata` dataclass (interchange format)
- [x] EPUB metadata extraction via ebooklib
- [x] EPUB metadata writing (round-trip safe)
- [x] CLI skeleton: `bookery import <dir>`, `bookery inspect <file>`
- [x] Tests: unit (27), integration (5), e2e (10) — 42 total

## Phase 2: Metadata Matching (Open Library)
- [x] `MetadataProvider` protocol
- [x] `MetadataCandidate` dataclass (metadata + confidence + source)
- [x] Open Library provider: ISBN lookup
- [x] Open Library provider: title+author search fallback
- [x] Confidence scoring
- [x] Rate limiting / respectful API usage
- [x] Interactive review flow (accept/edit/skip per book)
- [x] Non-destructive write-back (copy file, then write metadata to copy)
- [x] Tests for provider, matching, and review flow

## Phase 3: Database + Catalog
- [x] SQLite wrapper (thin, no ORM)
- [x] Schema: books, tags, book_tags (book_attributes deferred to Phase 4, device_syncs to Phase 6)
- [x] Version-stamped forward migrations (V1 → V2 runner in connection.py)
- [x] FTS5 (full-text search on title, author, series, description)
- [x] Import pipeline: extract → match → confirm → write to DB
- [x] Idempotent import (file_hash dedup)
- [x] `bookery verify` command (detect moved/missing files, --check-hash)
- [x] `bookery tag` command group (add, rm, ls)
- [x] `bookery info` shows tags, `bookery ls --tag` filter

## Phase 4: Query + Search + Browse
- [ ] Hand-rolled recursive descent parser
- [ ] Query types: FieldQuery, SubstringQuery, RegexpQuery, NotQuery, AndQuery, OrQuery
- [ ] Bare text → FTS5, field:value → WHERE clause
- [x] `bookery ls` with `--series` / `--tag` filters, sort, pagination
- [x] `bookery info <id>` detailed view
- [x] `bookery tag add/rm/ls`
- [ ] `bookery edit` interactive metadata editor (in-CLI; web UI ships the edit flow)
- [x] Output modes: table (Rich), --json
- [ ] Search < 200ms on 2000-book library (not yet benchmarked)

## Phase 5: Multi-Provider Metadata
- [x] Google Books provider alongside Open Library
- [x] Consensus merger across providers (≥2 agree → win, else priority order)
- [x] Provider response cache (`metadata_cache.db`, TTL configurable)
- [x] ISBN-10/13 normalization
- [x] Per-field provenance table (`book_field_provenance`)
- [x] Field-level lock/unlock via `bookery info --lock` / `--unlock`
- [x] Hand-edit support via `bookery info --set field=value` (stamped as `user`)

## Phase 6: Kobo Device Sync
- [x] Kobo detection (auto-scan mount points)
- [x] `bookery sync kobo` — convert EPUBs to `.kepub.epub` and copy to device
- [x] `--target <path>` override and `--dry-run`
- [x] Sync caching keyed on source hash + kepubify version (`kepub_cache.db`)
- [x] Additive sync (existing device files never deleted)
- [x] Tested against real Kobo hardware
- [ ] `bookery device ls` — list books on device (not yet implemented)
- [ ] `bookery device rm <query>` — remove from device (not yet implemented)

## Phase 7: Web UI
- [x] `bookery serve` — local Flask UI bound to 127.0.0.1
- [x] Paginated `/books` with `BrowseQuery` + result count
- [x] Sortable column headers
- [x] Filter chips
- [x] Responsive mobile card layout
- [x] Cover thumbnails on list and detail
- [x] Per-book detail and edit pages (real URLs, `?return_to` threading)
- [x] Search active metadata providers from the UI
- [x] Apply candidate metadata with side-by-side diff
- [x] Delete book from detail page
- [x] Persistent book context subhead on sub-flows
- [x] Create and edit collections from the UI (incl. raw rule strings) with inline validation

## Phase 8: Vault-Export
- [x] Obsidian vault → single EPUB pipeline (pandoc)
- [x] Hierarchical folder/note TOC
- [x] A-Z letter buckets within each folder
- [x] Leading-article-aware filing (The/A/An stripped; `filing_title` frontmatter override)
- [x] One TOC entry per note (body H1-H6 demoted)
- [x] `[[wiki-link]]` and `![[image]]` embed resolution
- [x] Optional tag index
- [x] `--catalog` flag: auto-import the export into the library
- [x] Stable UUID across re-exports for in-place Kobo updates
- [x] `exclude_tags` to drop ephemeral notes (meetings, dailies)

## Phase 9: Plugin Architecture (Next)
- [ ] pluggy hookspecs (extract_metadata, match_metadata, detect_device, etc.)
- [ ] Plugin manager: discovery via entry_points
- [ ] Refactor EPUB format as built-in plugin
- [ ] Refactor Open Library + Google Books as built-in plugins
- [ ] `bookery plugins` command
- [ ] `prepare_for_device` hook (kepub conversion path)

## Phase 10: Polish
- [x] Progress bars (Rich) for import and sync
- [x] `bookery verify` — scan for missing/moved/changed files
- [x] `bookery prune` — remove catalog rows with missing files
- [x] Test guardrail: tests can no longer touch real `~/.bookery`
- [ ] Cover extraction + cache (`~/.config/bookery/covers/`)
- [ ] Pydantic config model (TOML + env var + CLI flag layering)
- [ ] Performance benchmarks (search, import rate)
- [ ] E2e test suite covering full user flows

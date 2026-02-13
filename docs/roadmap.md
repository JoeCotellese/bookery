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

## Phase 4: Query DSL + Search + Browse
- [ ] Hand-rolled recursive descent parser
- [ ] Query types: FieldQuery, SubstringQuery, RegexpQuery, NotQuery, AndQuery, OrQuery
- [ ] Bare text → FTS5, field:value → WHERE clause
- [ ] `bookery ls` with query filters, sort, pagination
- [ ] `bookery info <query>` detailed view
- [ ] `bookery tag add/rm`
- [ ] `bookery edit` interactive metadata editor
- [ ] Output modes: table (Rich), --json, --quiet
- [ ] Search < 200ms on 2000-book library

## Phase 5: Plugin Architecture
- [ ] pluggy hookspecs (extract_metadata, match_metadata, detect_device, etc.)
- [ ] Plugin manager: discovery via entry_points
- [ ] Refactor EPUB format as built-in plugin
- [ ] Refactor Open Library as built-in plugin
- [ ] `bookery plugins` command
- [ ] `prepare_for_device` hook (kepub conversion path)

## Phase 6: Kobo Device Integration
- [ ] Kobo detection (scan /Volumes, verify .kobo/ directory)
- [ ] `bookery send <query>` — copy books to device
- [ ] `bookery device ls` — list books on device
- [ ] `bookery device rm <query>` — remove from device
- [ ] Device sync tracking (device_syncs table)
- [ ] Free space reporting, --dry-run
- [ ] Test against real Kobo hardware

## Phase 7: Polish
- [ ] Cover extraction + cache (~/.config/bookery/covers/)
- [ ] Progress bars (Rich) for import and send
- [ ] Pydantic config model (YAML, env var, CLI flag layering)
- [ ] `bookery verify` — scan for missing/moved/changed files
- [ ] Performance benchmarks (search, import rate)
- [ ] E2e test suite covering full user flows

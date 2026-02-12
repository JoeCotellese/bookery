# Bookery

CLI-first ebook library manager. EPUB-focused, metadata-first, non-destructive.

## Architecture

- **`BookMetadata`** (`metadata/types.py`) is the interchange format — everything flows through it
- **`MetadataProvider`** protocol (`metadata/provider.py`) — implement this to add new sources
- **`MetadataCandidate`** wraps metadata + confidence + source for the review pipeline
- Pipeline: extract → normalize → search → score → review → write copy
- Non-destructive: originals are never modified, always copy-then-write

## Key Conventions

- All code files start with two `# ABOUTME:` comment lines describing the file's purpose
- Tests are mandatory: unit, integration, and e2e for every feature
- TDD: write failing test first, then minimal code to pass
- Never modify original EPUB files — work on copies in output directory

## Package Layout

- `cli/` — Click commands, Rich output (no business logic here)
- `core/` — Pipeline logic (write-back, future import pipeline)
- `formats/` — File format handlers (EPUB via ebooklib)
- `metadata/` — Matching engine (providers, scoring, normalization, candidates)
- `db/` — Database layer (planned — SQLite, no ORM)
- `device/` — Device sync (planned — Kobo first)
- `plugins/` — Plugin architecture (planned — pluggy)

## Tools

- **uv** for dependency management and running
- **pytest** for tests (`uv run pytest`)
- **ruff** for linting (`uv run ruff check src/ tests/`)

## Standards

Full coding standards and contribution guide: [CONTRIBUTING.md](CONTRIBUTING.md)

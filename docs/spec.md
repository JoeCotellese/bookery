# Bookery — Feature Specification

## Problem Statement

Managing a moderate-to-large ebook collection (500-2000 books) and sending books to a Kobo e-reader requires either manual file wrangling or Calibre — which is powerful but heavyweight. Calibre's pain points include: slow startup, complex UI for simple tasks, opaque database that reorganizes your filesystem, and feature bloat for users who just want to **find a book and put it on their Kobo**.

## Target User

A technically literate ebook collector who:
- Owns a Kobo e-reader (USB-connected)
- Has a collection of mostly EPUB files (500-2000 books)
- Wants to quickly search, browse, and send books to the device
- Values speed, simplicity, and control over their file organization
- Is comfortable with CLI and may want TUI/WebUI later

## Architectural Model: beets

Bookery follows the [beets](https://beets.io/) model — a music library manager for the command line. Key patterns borrowed:

- **Import workflow** — interactive matching/confirmation when cataloging
- **Query DSL** — `field:value` syntax, combinable, powerful but learnable
- **Autotagger pipeline** — match against external sources, present candidates, let user confirm
- **Plugin hooks** — events throughout the pipeline that plugins can tap into
- **Layered architecture** — core library separated from UI (CLI first, TUI/WebUI later)
- **YAML configuration**
- **SQLite catalog**
- **Non-destructive by default**

## Key Differentiators from Calibre

| Aspect | Calibre | Bookery |
|--------|---------|---------|
| Startup | Heavy GUI, slow launch | Instant CLI, sub-second |
| File organization | Reorganizes into its own structure | Works with your existing filesystem |
| Database | Opaque SQLite, Calibre-specific | Portable, simple metadata store |
| Scope | Everything (conversion, editing, news, stores) | Focused: catalog + send to device |
| Extensibility | Monolithic plugins | Plugin architecture from day one |
| UI | One heavyweight GUI | Layered: CLI → TUI → WebUI |

## Design Principles

1. **Non-destructive**: Never move, rename, or reorganize the user's files without explicit request
2. **Fast**: Sub-second for common operations (search, list, send)
3. **Portable**: Metadata should be exportable/inspectable, no lock-in
4. **Pluggable**: Format support, metadata sources, and device targets via plugins
5. **Unix philosophy**: Do one thing well, compose with other tools

---

## User Stories

### Epic 1: Library Import & Cataloging

#### US-1.1: Import ebook files (beets-style interactive import)

> As a user, I want to import ebooks into my catalog with interactive metadata matching, so that my library is well-organized from the start.

*Acceptance Criteria:*
- Given a directory path, when I run `bookery import`, EPUB files are discovered recursively
- For each file, metadata is extracted (title, author, language, publisher, ISBN, cover)
- If an external metadata source plugin is installed, candidates are matched and presented
- User confirms, edits, or skips each match interactively
- Files already in the catalog are not re-processed (idempotent)
- `--quiet` flag auto-accepts best matches without confirmation
- Progress is reported during import (count, current file)
- Import of 2000 EPUBs completes in under 60 seconds

*Edge Cases:*
- Corrupt/unreadable EPUB files → log warning, skip, continue
- Duplicate files (same book, different paths) → detect and flag, configurable action (ask/skip/keep)
- Missing metadata fields → store what's available, mark incomplete
- Symlinks → follow by default, flag circular references

#### US-1.2: Search the library

> As a user, I want to search my library using a query DSL so that I can quickly find books.

*Acceptance Criteria:*
- Query DSL supports: `field:value` (exact), `field::regex` (regex), negation (`^`), AND (space), OR (comma)
- Full-text search across title and author fields
- Results returned in under 200ms for a 2000-book library
- Results show: title, author, format, file size, tags, and whether it's on the Kobo

#### US-1.3: Browse and filter the library

> As a user, I want to list and filter my library by author, tag, or format so that I can explore my collection.

*Acceptance Criteria:*
- `bookery ls` lists all books with optional query filters
- Sort by title, author, date added, file size
- Paginated output for CLI (configurable page size)
- Three output modes: table (default), `--json`, `--quiet` (IDs only)

#### US-1.4: View book details

> As a user, I want to view detailed metadata for a specific book so I can verify it before sending.

*Acceptance Criteria:*
- `bookery info <query>` shows all extracted metadata fields
- Shows file path, size, format
- Shows device status (on Kobo or not, when last sent)
- Shows cover image path (for TUI/WebUI to render later)

### Epic 2: Kobo Device Integration

#### US-2.1: Detect connected Kobo

> As a user, I want the tool to automatically detect my Kobo when connected via USB.

*Acceptance Criteria:*
- Auto-detect Kobo mount point on macOS (scan `/Volumes/`)
- Verify it's a Kobo by checking for `.kobo/` directory
- Report device model, storage capacity, and free space
- Fallback: manual mount path via config or `--device` flag

*Edge Cases:*
- Multiple Kobos connected → list them, let user choose
- Kobo not mounted → clear error message with troubleshooting hint
- Read-only mount → detect and warn before attempting copy

#### US-2.2: Send books to Kobo

> As a user, I want to send one or more books to my Kobo so I can read them on the device.

*Acceptance Criteria:*
- `bookery send <query>` sends matching books
- Send single book by ID, title search, or file path
- Send multiple books (batch send by query/tag/filter)
- Copy files to Kobo's internal storage
- Track which books have been sent (avoid re-sending)
- Report success/failure for each book
- Show free space before and after transfer
- `--dry-run` flag to preview without sending

*Edge Cases:*
- Insufficient space on Kobo → warn before transfer, show what fits
- Book already on device → skip with notice (or `--force` flag)
- USB disconnected mid-transfer → graceful handling, report partial state
- Large batch → progress indicator

#### US-2.3: List and remove books from Kobo

> As a user, I want to see what's on my Kobo and remove books I've finished.

*Acceptance Criteria:*
- `bookery device ls` lists books currently on the device
- `bookery device rm <query>` removes matching books
- Confirm before deletion (unless `--yes` flag)
- Batch remove supported (by query)
- Update tracking metadata after removal

### Epic 3: Metadata Management

#### US-3.1: Edit book metadata

> As a user, I want to edit a book's metadata so I can correct or enrich my catalog.

*Acceptance Criteria:*
- `bookery edit <query>` opens interactive metadata editor
- Editable fields: title, author, series, series index, tags, language
- Changes stored in the catalog (not written to EPUB by default)
- `--write` flag to persist changes back to the EPUB file
- Batch tag operations: `bookery tag add <tag> <query>`, `bookery tag rm <tag> <query>`

#### US-3.2: Tag books

> As a user, I want to tag books with custom labels so I can organize and filter.

*Acceptance Criteria:*
- Add/remove arbitrary string tags
- `bookery tags` lists all tags with book counts
- Filter library by tag(s) via query DSL: `tag:to-read`
- Tags are lightweight strings, no hierarchy required for v1

### Epic 4: Plugin Architecture

#### US-4.1: Format plugins

> As a user, I want to add support for additional ebook formats via plugins.

*Acceptance Criteria:*
- Core ships with EPUB support only
- Plugin interface for: metadata extraction, format detection, (future) conversion
- Plugins are discoverable Python packages (entry points)
- Missing plugin for a format → clear message ("install bookery-mobi for MOBI support")

#### US-4.2: Metadata source plugins

> As a user, I want to enrich my catalog with metadata from external sources.

*Acceptance Criteria:*
- Plugin interface for metadata lookup by ISBN, title+author
- Results presented for user confirmation before applying
- Rate limiting and caching for external APIs
- Core plugin candidates: Open Library, Google Books, Goodreads

---

## UX Design: CLI Interaction

### Command Structure

```
bookery <command> [subcommand] [query] [flags]
```

### Commands

```bash
# Import / Scan
bookery import ~/Books              # Interactive import workflow
bookery import ~/Books --quiet      # Auto-accept best matches

# Query / Browse
bookery ls                          # List all books
bookery ls author:"Umberto Eco"     # Query by field
bookery ls tag:to-read format:epub  # Compound query
bookery info "Name of the Rose"     # Detailed single-book view

# Device
bookery send "Name of the Rose"     # Send single book
bookery send tag:vacation           # Send all books matching query
bookery device                      # Show connected Kobo info
bookery device ls                   # List books on device
bookery device rm "Old Book"        # Remove from device

# Metadata
bookery tag add to-read "Book Title"    # Add tag
bookery tag rm to-read "Book Title"     # Remove tag
bookery edit "Book Title"               # Interactive metadata edit

# Plugins
bookery plugins                     # List installed plugins
```

### Query DSL

```
field:value          # Exact match
field::regex         # Regex match
field:value1..value2 # Range (for dates, ratings)
field:               # Field is empty/missing
^query               # Negate
query1 , query2      # OR (comma)
query1 query2        # AND (space)
```

### Import Workflow (beets-style)

```
$ bookery import ~/Books/new-acquisitions/

Scanning 12 files...

[1/12] the_name_of_rose.epub
  Extracted:  "The Name of the Rose" - Unknown Author
  Match:      "The Name of the Rose" - Umberto Eco (Open Library, 95% confidence)
  Apply match? [Y/n/edit/skip]

[2/12] project_hail_mary.epub
  Extracted:  "Project Hail Mary" - Andy Weir
  No corrections needed.
  Cataloging... done.

[3/12] corrupted_file.epub
  ⚠ Could not read file (invalid EPUB structure)
  Skip and continue? [Y/n]
```

### Output Modes

**Default (table):**
```
$ bookery ls author:"Eco"
  ID   Title                      Author        Tags         Format  Size
  142  The Name of the Rose       Umberto Eco   favorites    epub    1.2M
  143  Foucault's Pendulum        Umberto Eco   to-read      epub    890K
  144  The Prague Cemetery         Umberto Eco                epub    1.1M

3 books found.
```

**JSON:** `bookery ls author:"Eco" --json`

**Quiet (IDs only):** `bookery ls author:"Eco" --quiet`

### Device Send UX

```
$ bookery send tag:vacation

Kobo Clara HD detected at /Volumes/KOBOeReader
Free space: 2.1 GB

Sending 5 books (4.2 MB total):
  ✓ The Name of the Rose (1.2M)
  ✓ Project Hail Mary (890K)
  ✓ Piranesi (720K)
  ✓ Klara and the Sun (680K)
  ✓ Anxious People (750K)

5/5 sent. Free space remaining: 2.1 GB
```

### Configuration

```yaml
# ~/.config/bookery/config.yaml
library:
  path: ~/Books
  database: ~/.config/bookery/library.db

import:
  autotag: yes
  confirm: yes
  quiet: no
  duplicate_action: ask  # ask | skip | keep

device:
  auto_detect: yes
  mount_path: null
  directory: /

output:
  color: auto    # auto | always | never
  format: table  # table | json | quiet

plugins:
  - mobi
  - openlibrary
  - goodreads
```

### Accessibility (CLI)

- All information conveyed by color also conveyed by text/symbols
- `--json` output for screen readers and tooling
- `--no-color` flag and `NO_COLOR` env var support
- Structured, predictable output format

---

## Out of Scope (v1)

- Format conversion (MOBI→EPUB, etc.) — future plugin
- Kobo cloud/wireless sync — USB only for v1
- Reading progress sync from Kobo
- Built-in ebook reader/viewer
- Store/purchase integration
- Automatic cover art downloading — future plugin
- OPDS server — interesting for v2 WebUI

## Performance Targets

| Metric | Target |
|--------|--------|
| Scan speed | 2000 EPUBs in < 60s |
| Search speed | Results in < 200ms |
| Send to device | Single book < 3s |
| Startup time | CLI ready in < 500ms |
| Time to "find and send" | Under 10 seconds end-to-end |
| Plugin load time | < 100ms per plugin |

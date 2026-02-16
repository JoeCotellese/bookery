# Bookery

A CLI-first ebook library manager inspired by [beets](https://beets.io/) and [Calibre](https://calibre-ebook.com/). Fix your metadata, organize your library, sync to your Kobo — all from the terminal.

Bookery takes the "metadata-first" approach that made beets great for music and applies it to ebooks. It matches your EPUBs against online sources, lets you review and correct metadata interactively, and keeps your originals untouched.

## Status

**Early development** — Bookery is functional but not yet feature-complete. EPUB metadata extraction, MOBI-to-EPUB conversion, matching against Open Library, SQLite catalog, and non-destructive write-back are working. Device sync and plugins are on the roadmap.

See [docs/roadmap.md](docs/roadmap.md) for the full plan.

## Features

- **EPUB metadata extraction** — reads title, author, ISBN, language, publisher, description, cover, and identifiers from any EPUB
- **MOBI-to-EPUB conversion** — converts MOBI/KF8 files to EPUB, preserving metadata, images, cover art, and chapter structure (via NCX TOC)
- **Open Library matching** — searches by ISBN (precise) or title/author (fuzzy), with confidence scoring
- **Interactive review** — presents candidates in a Rich table, lets you accept, compare details, look up by URL, or skip
- **Smart normalization** — splits mangled filenames like `SteveBerry-TheTemplarLegacy` into clean search queries, detects embedded author names
- **SQLite catalog** — imports books into a local database for querying, tagging, and integrity checks
- **Non-destructive** — never modifies your original files; writes corrected copies to an output directory

## Installation

Requires Python 3.12+.

```bash
# Clone and install with uv
git clone https://github.com/joecotellese/bookery.git
cd bookery
uv sync
```

## Quick Start

```bash
# Inspect a single EPUB
bookery inspect ~/Books/some-book.epub

# Scan a directory and report format coverage
bookery inventory ~/Books/

# Convert MOBI files to EPUB
bookery convert ~/Books/ -o ~/Books-epub/

# Match EPUBs against Open Library and write corrected copies
bookery match ~/Books/ -o ~/Books-fixed/

# Auto-accept high-confidence matches (no prompts)
bookery match ~/Books/ -o ~/Books-fixed/ --quiet

# Import matched EPUBs into the catalog
bookery import ~/Books-fixed/ --db ~/library.db

# Search and browse the catalog
bookery search "martian"
bookery ls --tag fiction
bookery info 42
```

## Commands

### Metadata & Matching

| Command | Description |
|---------|-------------|
| `inspect <file>` | Show metadata extracted from an EPUB file |
| `match <path> -o <dir>` | Match EPUBs against Open Library and write corrected copies |
| `rematch [book_id]` | Re-run matching on cataloged books and update the database |

### Conversion

| Command | Description |
|---------|-------------|
| `convert <path> -o <dir>` | Convert MOBI files to EPUB format (supports `--match` to chain into matching) |

### Library Catalog

| Command | Description |
|---------|-------------|
| `import <dir>` | Scan for EPUBs and catalog them in the library (supports `--match` to match first) |
| `ls` | List all books in the catalog (filter with `--series` or `--tag`) |
| `info <id>` | Show detailed metadata for a book by ID |
| `search <query>` | Search the catalog by title, author, or description |
| `inventory <path>` | Scan a directory tree and report ebook format coverage |

### Organization

| Command | Description |
|---------|-------------|
| `tag add <id> <tag>` | Add a tag to a book |
| `tag rm <id> <tag>` | Remove a tag from a book |
| `tag ls` | List all tags with book counts |
| `verify` | Check for missing or changed files (supports `--check-hash`) |

### The `match` workflow

When you run `bookery match`, Bookery will:

1. Extract metadata from each EPUB
2. Normalize mangled titles (CamelCase splitting, word segmentation)
3. Search Open Library by ISBN first, then fall back to title/author
4. Present you with scored candidates to review
5. Write your chosen metadata to a copy of the file

During review, you can:
- **[1-N]** Accept a candidate
- **[v1-vN]** View a side-by-side comparison
- **[u]** Look up a specific Open Library URL
- **[s]** Skip this book
- **[k]** Keep the original metadata

## Project Structure

```
src/bookery/
  cli/            # Click commands
  core/           # Pipeline logic (non-destructive write-back, conversion)
  formats/        # Format handlers (EPUB via ebooklib, MOBI via KindleUnpack)
  metadata/       # Matching engine
    openlibrary.py    # Open Library API provider
    scoring.py        # Weighted confidence scoring
    normalizer.py     # Title/author normalization (CamelCase, wordninja)
    candidate.py      # MetadataCandidate dataclass
    provider.py       # MetadataProvider protocol
  db/             # SQLite catalog (schema, CRUD, search, migrations)
```

## Development

```bash
# Install dev dependencies
uv sync

# Run tests
uv run pytest

# Run linter
uv run ruff check src/ tests/

# Run a specific test file
uv run pytest tests/unit/test_scoring.py -v
```

## Roadmap

Bookery is being built in phases:

1. ~~EPUB metadata read/write + CLI skeleton~~
2. ~~Open Library matching + interactive review~~
3. ~~SQLite catalog, import pipeline, query commands~~
4. ~~MOBI-to-EPUB conversion~~
5. **Next:** Plugin architecture (format and provider plugins)
6. Kobo device integration
7. Polish (config, covers, progress bars, performance)

See [docs/roadmap.md](docs/roadmap.md) for detailed checklists.

## Design Principles

- **Metadata-first** — get the data right before organizing files
- **Non-destructive** — original files are never modified
- **CLI-first** — every feature is a terminal command; no GUI required
- **Extensible** — providers, formats, and devices will be pluggable
- **Respectful** — rate-limited API usage, no scraping

## Contributing

Bookery is AI-friendly and developed with the help of [Claude Code](https://docs.anthropic.com/en/docs/claude-code). AI-assisted contributions are welcome alongside traditional ones.

See [CONTRIBUTING.md](CONTRIBUTING.md) for coding standards, testing requirements, and how to get started.

## License

[MIT](LICENSE)

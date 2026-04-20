# Bookery

A CLI-first ebook library manager inspired by [beets](https://beets.io/) and [Calibre](https://calibre-ebook.com/). Fix your metadata, organize your library, sync to your Kobo — all from the terminal.

Bookery takes the "metadata-first" approach that made beets great for music and applies it to ebooks. It matches your EPUBs against online sources, lets you review and correct metadata interactively, and keeps your originals untouched.

## Status

**Early development** — Bookery is functional but not yet feature-complete. EPUB metadata extraction, MOBI-to-EPUB conversion, matching against Open Library, SQLite catalog, and non-destructive write-back are working. Device sync and plugins are on the roadmap.

See [docs/roadmap.md](docs/roadmap.md) for the full plan.

## Features

- **EPUB metadata extraction** — reads title, author, ISBN, language, publisher, description, cover, and identifiers from any EPUB
- **MOBI-to-EPUB conversion** — converts MOBI/KF8 files to EPUB, preserving metadata, images, cover art, and chapter structure (via NCX TOC)
- **PDF-to-EPUB conversion** — `bookery add` and `bookery import` detect text-based PDFs, extract their structure with pdfplumber + a local LLM (LM Studio), and produce a reflowable EPUB. Scanned PDFs are refused (OCR not yet supported).
- **Kobo sync** — `bookery sync kobo` walks the catalog, converts each EPUB to `.kepub.epub` via `kepubify`, and copies the result to a mounted Kobo. The library itself stays format-canonical (EPUB only); kepub is generated on demand at sync time and cached so re-syncs are free when nothing has changed.
- **Open Library matching** — searches by ISBN (precise) or title/author (fuzzy), with confidence scoring
- **Interactive review** — presents candidates in a Rich table, lets you accept, compare details, look up by URL, or skip
- **Smart normalization** — splits mangled filenames like `SteveBerry-TheTemplarLegacy` into clean search queries, detects embedded author names
- **SQLite catalog** — imports books into a local database for querying, tagging, and integrity checks
- **Non-destructive** — metadata writes always go to a copy; original file contents are never modified. `import` copies each source into your library by default (`--move` deletes the source after a successful catalog insert)

## Installation

Requires Python 3.12+.

```bash
# Clone and install with uv
git clone https://github.com/joecotellese/bookery.git
cd bookery
uv sync
```

### Optional: PDF conversion

The PDF path in `bookery add` / `bookery import` routes the document
through a single semantic LLM call that reassembles articles/chapters
into a clean EPUB. You'll need an OpenAI-compatible endpoint with a
model strong enough to return structured JSON.

**Local (default)** — [LM Studio](https://lmstudio.ai) with a long-
context instruct model (known-good: **Qwen 2.5 7B Instruct 1M**).
Load the model with ≥16k context, enable the local server, then point
bookery at it via `~/.bookery/config.toml`:

```toml
[convert.semantic]
provider = "lm-studio"
model = "qwen2.5-7b-instruct-1m"
base_url = "http://localhost:1234/v1"
api_key_env = ""             # empty for local; no key needed
prompt_version = 1
llm_max_retries = 2
```

**Cloud** — swap `provider`, `model`, `base_url`, and point
`api_key_env` at the env var holding your key. Never write the key
into `config.toml`:

```toml
[convert.semantic]
provider = "openai"
model = "gpt-5.4-nano"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
prompt_version = 1
```

See [`docs/config.example.toml`](docs/config.example.toml) for a fully
annotated config with LM Studio, Moonshot/Kimi, and OpenAI examples.

Semantic responses are cached under `~/.bookery/data/convert_cache.db`
so re-runs on the same PDF skip the LLM. Safe to delete at any time;
bumping `prompt_version` invalidates only stale entries.

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
bookery match ~/Books/ -o ~/Books-fixed/ --yes

# Import EPUBs into the catalog (copies into ~/.library/ by default)
bookery --db ~/library.db import ~/Books/

# Import and remove the sources after they land in the library
bookery --db ~/library.db import ~/Downloads/ --move

# Search and browse the catalog
bookery search "martian"
bookery ls --tag fiction
bookery info 42
```

### Common options

- **`--db PATH`** is a top-level option; put it before the subcommand so every command picks it up: `bookery --db ~/library.db ls`. Subcommand-level `--db` still works and overrides the global.
- **`-y/--yes`** auto-accepts high-confidence matches without prompting (valid on `add`, `import`, `match`, `rematch`, `convert`). `-q/--quiet` is a deprecated alias.
- **`-t/--threshold`** sets the confidence cutoff for auto-accept. The default comes from `[matching].auto_accept_threshold` in `~/.bookery/config.toml` (default `0.8`):

  ```toml
  [matching]
  auto_accept_threshold = 0.85
  cache_ttl_days = 30        # metadata response cache TTL (default 30)
  providers = ["openlibrary", "googlebooks"]   # priority order; default ["openlibrary"]
  ```

- **`--no-cache`** on `match`/`rematch` bypasses the on-disk metadata response cache and forces fresh provider lookups. Cached responses live at `{data_dir}/metadata_cache.db` and expire after `[matching].cache_ttl_days`.
- **`[matching].providers`** selects and orders metadata sources. With a single entry the named provider is used directly; with two or more, results are merged by a consensus step that prefers values agreed on by ≥2 providers and falls back to the priority order otherwise. Supported: `openlibrary`, `googlebooks`.

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
| `vault-export --vault <path> -o <file>` | Export an Obsidian vault to a single EPUB with clickable TOC, resolved wiki-links, and an optional tag index. Requires [pandoc](https://pandoc.org). |

### Library Catalog

| Command | Description |
|---------|-------------|
| `import <dir>` | Scan for EPUBs, copy into `library_root`, and catalog them (supports `--match`, `--move`) |
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

### Device sync

| Command | Description |
|---------|-------------|
| `sync kobo` | Convert library EPUBs to `.kepub.epub` and copy to a mounted Kobo |
| `sync kobo --target <path>` | Override auto-detection with an explicit mount point |
| `sync kobo --dry-run` | Show what would be copied without touching the device |

Requires the [`kepubify`](https://pgaskin.net/kepubify/) binary on `PATH`
(`brew install kepubify` on macOS). Files are written to
`<kobo>/Bookery/Author/Title/Title.kepub.epub` — the dedicated `Bookery/`
subdirectory keeps synced content visibly separate from Calibre
sideloads, Kobo store purchases, and library borrows. Sync is currently
**additive**: existing files on the device are never deleted. A SQLite
cache at `{data_dir}/kepub_cache.db` keyed on the source EPUB hash plus
the `kepubify` version makes re-syncs effectively free when nothing has
changed.

### The `vault-export` workflow

Turn an Obsidian vault into a single EPUB — one chapter per note, with a
clickable TOC, resolved `[[wiki-links]]` and `![[image]]` embeds, and an
optional tag index at the end. Requires [pandoc](https://pandoc.org)
(`brew install pandoc` on macOS).

Run with flags:

```bash
bookery vault-export --vault ~/obsidian-vault -o vault.epub \
  --folder "3_Permanent Notes" --folder "2_Literature Notes" \
  --index --exclude-tag type/meeting
```

Or set defaults once in `~/.bookery/config.toml` and just run
`bookery vault-export -o vault.epub`:

```toml
[vault_export]
vault_path = "~/obsidian-vault"
folders = ["3_Permanent Notes", "2_Literature Notes"]
include_index = true
index_exclude_prefixes = ["type/"]   # hide tags like `type/permanent` from index
index_min_count = 1
exclude_tags = ["type/meeting"]      # drop notes with these exact frontmatter tags
default_author = "Your Name"
uuid_mode = "stable"                 # "stable" keeps the same dc:identifier
                                     # across re-exports so Kobo updates in place
catalog = true                       # auto-add the EPUB to the bookery library
                                     # so it ships on the next `sync kobo`
```

`exclude_tags` matches the full tag string exactly (`type/meeting` skips
notes tagged `type/meeting` but not `type/permanent`). Callouts, block
references, note embeds (`![[note]]`), and Dataview queries are **not**
resolved in this version.

With `catalog = true` (or `--catalog` on the command line), the export is
imported into the library and then deployed to your reader on the next
`bookery sync kobo` — no separate `bookery add` step. A vault export is a
point-in-time snapshot, so re-running replaces the prior catalog row and
EPUB rather than piling up a new copy each day.

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
- **Non-destructive** — original file contents are never modified; metadata writes go to a copy in the library
- **CLI-first** — every feature is a terminal command; no GUI required
- **Extensible** — providers, formats, and devices will be pluggable
- **Respectful** — rate-limited API usage, no scraping

## Contributing

Bookery is AI-friendly and developed with the help of [Claude Code](https://docs.anthropic.com/en/docs/claude-code). AI-assisted contributions are welcome alongside traditional ones.

See [CONTRIBUTING.md](CONTRIBUTING.md) for coding standards, testing requirements, and how to get started.

## License

[MIT](LICENSE)

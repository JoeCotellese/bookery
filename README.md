# Bookery

A CLI-first ebook library manager inspired by [beets](https://beets.io/) and [Calibre](https://calibre-ebook.com/). Fix your metadata, organize your library, sync to your Kobo — all from the terminal.

Bookery takes the "metadata-first" approach that made beets great for music and applies it to ebooks. It matches your EPUBs against online sources, lets you review and correct metadata interactively, and keeps your originals untouched.

## Status

**Active development** — daily-driver usable. EPUB metadata extraction, MOBI/PDF-to-EPUB conversion, multi-provider matching (Open Library + Google Books) with consensus merging, a SQLite catalog with per-field provenance, non-destructive write-back, Kobo device sync, a local web UI for browsing/editing, and Obsidian vault-export are all working. Plugin architecture is the main item still on the roadmap.

See [docs/roadmap.md](docs/roadmap.md) for the full plan.

## Features

- **EPUB metadata extraction** — reads title, author, ISBN, language, publisher, description, cover, and identifiers from any EPUB
- **MOBI-to-EPUB conversion** — converts MOBI/KF8 files to EPUB, preserving metadata, images, cover art, and chapter structure (via NCX TOC)
- **PDF-to-EPUB conversion** — `bookery add` detects text-based PDFs, extracts their structure with pdfplumber + a local LLM (LM Studio), and produces a reflowable EPUB. Scanned PDFs are refused (OCR not yet supported).
- **Kobo sync** — `bookery sync kobo` walks the catalog, converts each EPUB to `.kepub.epub` via `kepubify`, and copies the result to a mounted Kobo. The library itself stays format-canonical (EPUB only); kepub is generated on demand at sync time and cached so re-syncs are free when nothing has changed.
- **Collections** — group books into named lists, either static (hand-picked) or rule-based (membership derived live from a query like `genre:"Science Fiction"` or `series:Dune`, so it stays current as the library grows). See `bookery collections`.
- **Collection shelves on device** — the same `bookery sync kobo` mirrors each collection to a Kobo shelf (`Shelf`/`ShelfContent`). Bookery owns only shelves whose `InternalName` is `bookery-<collection_id>`; a user-created shelf that shares a name is skipped, never overwritten. Unchanged shelves are skipped on re-sync (membership hash), and a shelf is removed once its collection is deleted. `bookery collections show <id> --sync-status` reports per-device shelf state.
- **Multi-provider metadata matching** — Open Library and Google Books in a consensus merger that prefers values agreed on by ≥2 providers and falls back to a priority order otherwise. ISBN-10/13 lookups are normalized and provider responses are cached.
- **Per-field provenance & locking** — every cataloged field records which provider supplied it and when. User edits are stamped as `user` and locked against `rematch`; individual fields can be locked/unlocked explicitly with `bookery info --lock` / `--unlock`.
- **Interactive review** — presents candidates in a Rich table, lets you accept, compare details, look up by URL, or skip
- **Smart normalization** — splits mangled filenames like `SteveBerry-TheTemplarLegacy` into clean search queries, detects embedded author names
- **SQLite catalog** — imports books into a local database for querying, tagging, and integrity checks
- **Web UI** — `bookery serve` launches a local browser UI for paginated/sortable browsing of the catalog, filter chips, cover thumbnails, a responsive mobile card layout, per-book detail/edit pages, collection create/edit (including raw rule strings) with inline validation, search-active-providers, and "apply candidate metadata with diff" rematch flow.
- **Genre management** — `bookery genre` auto-maps raw provider subjects to a canonical genre vocabulary, with `assign` / `apply` / `auto` / `stats` / `unmatched` for curation.
- **Obsidian vault-export** — `bookery vault-export` turns an Obsidian vault into a single EPUB with a hierarchical folder/note TOC, A-Z buckets within each folder, leading-article-aware filing ("The Loop" files under L), resolved `[[wiki-links]]` and `![[image]]` embeds, and an optional tag index. Can auto-catalog the export so it ships on the next Kobo sync.
- **Non-destructive** — metadata writes always go to a copy; original file contents are never modified. `add` copies each source into your library by default (`--move` deletes the source after a successful catalog insert)

## Installation

Requires Python 3.12+.

```bash
# Clone and install with uv
git clone https://github.com/joecotellese/bookery.git
cd bookery
uv sync
```

### Optional: PDF conversion

The PDF path in `bookery add` routes the document
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
# Inspect a single EPUB (loose file on disk)
bookery info ~/Books/some-book.epub

# Scan a directory and report format coverage
bookery inventory ~/Books/

# Convert MOBI files to EPUB
bookery convert ~/Books/ -o ~/Books-epub/

# Match EPUBs against Open Library and write corrected copies
bookery match ~/Books/ -o ~/Books-fixed/

# Auto-accept high-confidence matches (no prompts)
bookery match ~/Books/ -o ~/Books-fixed/ --yes

# Add a single EPUB to the catalog (copies into ~/.library/ by default)
bookery --db ~/library.db add ~/Books/dune.epub

# Add an entire directory of EPUBs (recursive)
bookery --db ~/library.db add ~/Books/

# Add and remove the sources after they land in the library
bookery --db ~/library.db add ~/Downloads/ --move

# Search and browse the catalog
bookery search "martian"
bookery ls --tag fiction
bookery info 42
```

### Common options

- **`--db PATH`** is a top-level option; put it before the subcommand so every command picks it up: `bookery --db ~/library.db ls`. Subcommand-level `--db` still works and overrides the global.
- **`-y/--yes`** auto-accepts high-confidence matches without prompting (valid on `add`, `match`, `rematch`, `convert`). `-q/--quiet` is a deprecated alias.
- **`-t/--threshold`** sets the confidence cutoff for auto-accept. The default comes from `[matching].auto_accept_threshold` in `~/.bookery/config.toml` (default `0.8`):

  ```toml
  [matching]
  auto_accept_threshold = 0.85
  cache_ttl_days = 30        # metadata response cache TTL (default 30)
  providers = ["openlibrary", "googlebooks"]   # priority order; default ["openlibrary"]
  ```

- **`--no-cache`** on `match`/`rematch` bypasses the on-disk metadata response cache and forces fresh provider lookups. Cached responses live at `{data_dir}/metadata_cache.db` and expire after `[matching].cache_ttl_days`.
- **`[matching].providers`** selects and orders metadata sources. With a single entry the named provider is used directly; with two or more, results are merged by a consensus step that prefers values agreed on by ≥2 providers and falls back to the priority order otherwise. Supported: `openlibrary`, `googlebooks`.
- **Per-field provenance** is recorded for every cataloged book in the `book_field_provenance` table. Use `bookery info <id> --provenance` to see which source supplied each field and when it was fetched. Use `bookery info <id> --set field=value` to hand-edit a value (it's stamped as `user` and locked against overwrite), and `--lock field` / `--unlock field` to gate fields against `rematch`.

## Commands

### Metadata & Matching

| Command | Description |
|---------|-------------|
| `match <path> -o <dir>` | Match metadata for loose EPUB files (not yet in the catalog) and write corrected copies |
| `rematch [book_id]` | Re-run matching on cataloged books and update the database |

### Conversion

| Command | Description |
|---------|-------------|
| `convert <path> -o <dir>` | Convert MOBI files to EPUB format (supports `--match` to chain into matching) |
| `vault-export --vault <path> -o <file>` | Export an Obsidian vault to a single EPUB with clickable TOC, resolved wiki-links, and an optional tag index. Requires [pandoc](https://pandoc.org). |

### Library Catalog

| Command | Description |
|---------|-------------|
| `add <path>` | Add a single EPUB/PDF or a directory of EPUBs to the library (copies into `library_root`, catalogs). Files default to `--match`; directories default to `--no-match`. Supports `--move`, `--convert`, `--force-duplicates`, `-o/--output-dir`. `import` is a deprecated alias. |
| `remove <id>...` | Delete one or more books from the catalog and disk (`-y` skips prompt; `--keep-file` keeps the file) |
| `prune` | Remove catalog rows whose underlying files are missing |
| `ls` | List all books in the catalog (filter with `--series` or `--tag`) |
| `info <id-or-path>` | Show metadata for a cataloged book by ID, or for a loose EPUB on disk. Catalog mode supports `--provenance`, `--set field=value`, `--lock field`, `--unlock field`. `inspect` is a deprecated alias. |
| `search <query>` | Search the catalog by title, author, or description |
| `inventory <path>` | Scan a directory tree and report ebook format coverage |
| `reveal <query>` | Open the on-disk folder for a book (`--print` to print the path instead). `folder` is a deprecated alias. |

### Organization

| Command | Description |
|---------|-------------|
| `tag add <id> <tag>` | Add a tag to a book |
| `tag rm <id> <tag>` | Remove a tag from a book |
| `tag ls` | List all tags with book counts |
| `genre assign <id> <genre>` | Assign a canonical genre to a book |
| `genre auto-assign` | Auto-assign genres from subjects for cataloged books |
| `genre auto` | Auto-map provider subjects to canonical genres across the catalog |
| `genre ls` | List all canonical genres with book counts |
| `genre stats` | Show the most common subjects that don't map to a canonical genre |
| `genre unmatched` | Show books with subjects but no genre assigned |
| `mark finished <id>` | Mark a book as finished (also `mark reading <id>`, `mark unread <id>`; supports `--bulk-from FILE`) |
| `verify` | Check for missing or changed files (supports `--check-hash`) |

### Collections

Collections group books into named lists. A collection is either **static**
(hand-picked membership) or **rule-based** (membership derived live from a
query). The two are mutually exclusive — a rule-based collection holds no
hand-picked rows, and its members are recomputed on every read, so it stays
current automatically as the library changes.

| Command | Description |
|---------|-------------|
| `collections create <name>` | Create a static collection (`-d/--description` optional) |
| `collections create <name> --query '<rule>'` | Create a rule-based collection, e.g. `--query 'genre:"Science Fiction"'` |
| `collections ls` | List collections with live book counts |
| `collections show <id>` | Show a collection's books; rule-based collections also show the rule and live match count (`--sync-status` for per-device shelf state) |
| `collections add-books <id> <book_id>...` | Add books to a static collection |
| `collections remove-books <id> <book_id>...` | Remove books from a static collection |
| `collections edit <id> --query '<rule>'` | Convert a static collection to rule-based |
| `collections edit <id> --clear-query` | Convert a rule-based collection to static, snapshotting current members |
| `collections preview --query '<rule>'` | Show which books a rule matches, without saving |
| `collections query-help` | Print the full query reference (fields, operators, dates, examples) |
| `collections rename <id> <new_name>` | Rename a collection |
| `collections rm <id>` | Delete a collection (books are not deleted) |

#### Rule query language

A rule query is a [Lucene](https://lucene.apache.org/)-style expression over a
whitelisted set of fields, parsed permissively and validated restrictively — an
unknown field, bad value, or unsupported shape is rejected with a message naming
what's allowed. Run `bookery collections query-help` for the in-terminal
reference.

| Field | Matches |
|-------|---------|
| `id` | exact book id |
| `title` | exact, phrase, or `prefix*` (left-anchored) |
| `author` | substring (contains) |
| `series` | exact |
| `genre` | exact canonical genre |
| `tag` | exact |
| `language` | exact |
| `publisher` | exact |
| `subject` | substring (contains) |
| `isbn` | exact |
| `year` | publication year — `=`, range, or comparison |
| `rating` | `=`, range, or comparison |
| `added` | date added (ISO `YYYY-MM-DD`) — `=`, range, or comparison |

Operators: `AND`, `OR`, `NOT`, grouping with `( )`, and `+`/`-` prefixes
(require/exclude). The numeric/date fields (`year`, `rating`, `added`) also
accept ranges `[a TO b]` (inclusive), `{a TO b}` (exclusive), open-ended `*`,
and comparisons `>=` `<=` `>` `<`. Fuzzy (`~`) and boost (`^`) are not
supported.

```text
series:Dune
genre:"Science Fiction" AND year:[2020 TO *]
rating:>=4
author:"Ursula K. Le Guin" NOT tag:reread
```

### Web UI

| Command | Description |
|---------|-------------|
| `serve` | Launch the local web UI (`--host`, `--port`; default `127.0.0.1:5000`) |

The web UI provides paginated and sortable browsing, filter chips, cover thumbnails, a responsive mobile card layout, per-book detail and edit pages, a "search active providers" flow that lets you apply candidate metadata with a side-by-side diff, and inline delete. When you apply a candidate, its cover image (if the provider offers one) is fetched and embedded into the non-destructive EPUB copy alongside the text fields; a cover-fetch failure is non-fatal — the text metadata still applies and the result message notes the cover was skipped.

Collections can be created and edited directly from the web UI. "New collection" (on the collections page) opens a form for the name, an optional description, and an optional raw rule query (the same Lucene subset as `collections create --query`); leave the query blank for a hand-picked static collection. Each collection's detail page has an "Edit" affordance for changing its name, description, and (for an already rule-based collection) its rule. Invalid input — a blank or duplicate name, or an unparseable rule — is reported inline on the form with the field whitelist hint, never as an error page.

### Device sync

| Command | Description |
|---------|-------------|
| `sync kobo` | Convert library EPUBs to `.kepub.epub`, copy to a mounted Kobo, and mirror collections to device shelves |
| `sync kobo --target <path>` | Override auto-detection with an explicit mount point |
| `sync kobo --dry-run` | Show what would be copied without touching the device |
| `collections show <id> --sync-status` | Show per-device shelf sync state for a collection |

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
  --include-folder "3_Permanent Notes" --include-folder "2_Literature Notes" \
  --index --exclude-tag type/meeting
```

`--folder` is accepted as a deprecated alias for `--include-folder` and will
be removed in a future release.

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
                                     # across re-exports so Kobo updates in place.
                                     # Pass `--random-ids` on the command line
                                     # for a fresh identifier per export.
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

Tests are isolated from your real `~/.bookery/library.db` by an autouse
guardrail. If you previously ran the suite without this guardrail and your
catalog now reports `source missing: /private/var/folders/.../pytest-of-...`,
see ["Recovering from test pollution"](CONTRIBUTING.md#recovering-from-test-pollution)
in `CONTRIBUTING.md`.

## Roadmap

Bookery is being built in phases:

1. ~~EPUB metadata read/write + CLI skeleton~~
2. ~~Multi-provider matching (Open Library + Google Books) with consensus merger and interactive review~~
3. ~~SQLite catalog, import pipeline, per-field provenance, query commands~~
4. ~~MOBI-to-EPUB conversion~~
5. ~~PDF-to-EPUB conversion (semantic, local-LLM)~~
6. ~~Kobo device sync~~
7. ~~Obsidian vault-export to EPUB~~
8. ~~Web UI for browse/search/edit~~
9. **Next:** Plugin architecture (format and provider plugins)
10. Polish (covers cache, performance benchmarks, config polish)

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

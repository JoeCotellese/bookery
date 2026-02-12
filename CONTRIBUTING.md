# Contributing to Bookery

Thanks for your interest in contributing! Bookery is built with the help of AI coding assistants (specifically [Claude Code](https://docs.anthropic.com/en/docs/claude-code)), and we welcome contributions from both humans and AI-assisted workflows.

## Getting Started

```bash
git clone https://github.com/JoeCotellese/bookery.git
cd bookery
uv sync
uv run pytest          # should be green before you start
```

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

## Before You Code

1. **Check the [roadmap](docs/roadmap.md)** to see what's planned
2. **Open an issue** to discuss your idea before starting work
3. **Create a feature branch** — never commit directly to main

Branch naming: `feature/<desc>`, `fix/<desc>`, or `hotfix/<desc>`.

## Code Standards

### Style

- **Ruff** is the linter and formatter. Run `uv run ruff check src/ tests/` before committing.
- Python 3.12+ features are encouraged (type unions with `|`, etc.).
- Line length limit is 99 characters.
- Match the style of surrounding code. Consistency within a file matters more than strict rules.

### File Headers

Every code file starts with two comment lines describing its purpose:

```python
# ABOUTME: Open Library metadata provider implementation.
# ABOUTME: Searches openlibrary.org by ISBN or title/author and returns scored candidates.
```

This makes it easy to `grep -r "ABOUTME"` to understand the codebase at a glance.

### Comments

- Write comments that explain *why*, not *what*.
- Don't refer to temporal context ("recently refactored", "new approach"). Comments should be evergreen.
- Don't remove existing comments unless they are provably false.

### Naming

- Don't name things "new", "improved", "enhanced", etc. Names should be evergreen.
- Be specific: `_ENRICH_DESCRIPTION_LIMIT` over `_LIMIT`.

### Keep It Simple

- Prefer simple, readable code over clever or compact code.
- Don't add abstractions for one-time operations.
- Don't add error handling for scenarios that can't happen.
- Don't add features beyond what was asked for.

## Testing

### Policy

Every change must have tests. No exceptions. We require:

- **Unit tests** — isolated, fast, in `tests/unit/`
- **Integration tests** — component interactions, in `tests/integration/`
- **End-to-end tests** — CLI-level, in `tests/e2e/`

### Practice

We follow TDD:

1. Write a failing test
2. Write the minimum code to make it pass
3. Refactor
4. Repeat

### Running Tests

```bash
uv run pytest                              # full suite
uv run pytest tests/unit/                  # unit only
uv run pytest tests/unit/test_scoring.py -v  # single file, verbose
```

Test output must be clean — no warnings, no captured errors unless explicitly tested.

## Architecture

### Core Abstraction: BookMetadata

`BookMetadata` is the interchange format. It flows through the entire pipeline:

```
EPUB file → extract → BookMetadata → normalize → search → score → review → write copy
```

All components consume or produce `BookMetadata`. If you're adding a new feature, think about where it touches this pipeline.

### Non-Destructive Writes

Bookery never modifies original files. The write pipeline copies the file to an output directory, then writes metadata to the copy. This is a hard rule.

### Adding a Metadata Provider

Implement the `MetadataProvider` protocol in `metadata/provider.py`:

- `search_by_isbn(isbn) -> list[MetadataCandidate]`
- `search_by_title_author(title, author) -> list[MetadataCandidate]`

See `metadata/openlibrary.py` for a complete example.

### Adding a Format

Format handlers live in `formats/`. Each format needs:

- A read function that returns `BookMetadata`
- A write function that accepts `BookMetadata`
- An error class for read/write failures

See `formats/epub.py` for the pattern.

## AI-Assisted Development

This project uses Claude Code for development. If you use Claude Code or another AI assistant:

- The `CLAUDE.md` file in the repo root provides project context that AI tools can read
- The coding standards in this file apply equally to AI-generated and human-written code
- AI-generated commits should include a `Co-Authored-By` trailer

## Submitting Changes

1. Ensure all tests pass: `uv run pytest`
2. Ensure linting passes: `uv run ruff check src/ tests/`
3. Push your branch and open a PR against `main`
4. PRs should include a summary of changes and a test plan

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).

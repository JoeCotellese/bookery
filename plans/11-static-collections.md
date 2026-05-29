# [plan-11] Static Collections — Manual Book Curation (issue #239)

## Overview

Vertical slice 1 of the Collections epic (#179). Users can organize books into hand-picked lists via CLI and Web UI. No query engine, no auto-updates — just explicit membership.

## Database

**SCHEMA_V11:**
- `collections` table: `id`, `name`, `description`, `created_at`, `updated_at`
- `collection_books` junction table: `collection_id`, `book_id`
- `name` has `UNIQUE COLLATE NOCASE` (duplicate names rejected at DB level with clear error)
- Junction table has `ON DELETE CASCADE` on both FKs so deleting a collection or a book cleans up membership automatically

## Files to Create / Modify

### Database & Catalog Layer
- `src/bookery/db/schema.py` — add `SCHEMA_V11` and append to `MIGRATIONS`
- `src/bookery/db/catalog.py` — add collection CRUD methods to `LibraryCatalog`

### CLI Layer
- `src/bookery/cli/commands/collection_cmd.py` — new file with `collections` command group
- `src/bookery/cli/__init__.py` — register `collections` command

### Web Layer
- `src/bookery/web/routes.py` — add `/collections/`, `/collections/<int:collection_id>`, and wire collection chips into book detail
- `src/bookery/web/__init__.py` — register routes if needed
- New templates: `templates/collections_list.html`, `templates/collection_detail.html`, partials `_collections_list.html`, `_collection_detail.html`
- Update `templates/detail.html` and `_detail.html` to show collections chip group

### Tests
- `tests/unit/test_collections_crud.py` — catalog method unit tests
- `tests/unit/test_collection_commands.py` — CLI command unit tests
- `tests/integration/test_collections_workflow.py` — integration tests
- `tests/e2e/test_collection_cli.py` — e2e CLI tests via CliRunner
- `tests/web/test_collections.py` — web route tests

## Implementation Order (TDD)

### Phase 1: Database + Catalog

**Task 1.1: Schema migration**
- Test: `test_migration_applies` — open a temp DB and assert `collections` and `collection_books` tables exist
- Code: Add `SCHEMA_V11` to `schema.py`, append `(11, SCHEMA_V11)` to `MIGRATIONS`

**Task 1.2: `create_collection`**
- Test: `test_create_collection` — create a collection, assert it exists with correct name/description
- Test: `test_create_duplicate_name_raises` — attempt duplicate, assert clear error
- Code: `LibraryCatalog.create_collection(name, description=None) -> int`

**Task 1.3: `get_collection_by_id` and `get_collection_by_name`**
- Test: `test_get_collection_by_id`, `test_get_collection_by_name`, `test_get_nonexistent_returns_none`
- Code: getter methods returning a `CollectionRecord` dataclass or dict

**Task 1.4: `add_books_to_collection` and `remove_books_from_collection`**
- Test: `test_add_books`, `test_remove_books`, `test_add_invalid_book_raises`, `test_add_invalid_collection_raises`
- Code: bulk insert/delete on `collection_books`

**Task 1.5: `list_collections` and `get_collection_books`**
- Test: `test_list_collections_with_counts`, `test_get_collection_books_ordered`
- Code: `list_collections()` returns `[(id, name, description, book_count)]`, `get_collection_books(collection_id)` returns `list[BookRecord]`

**Task 1.6: `delete_collection` and `rename_collection`**
- Test: `test_delete_collection_cascades`, `test_rename_collection`, `test_rename_to_duplicate_raises`
- Code: `delete_collection(id)` and `rename_collection(id, new_name)`

### Phase 2: CLI

**Task 2.1: `collections create`**
- Test: `test_create_collection_success`, `test_create_duplicate_shows_error`
- Code: `collection_cmd.py` with `create` subcommand

**Task 2.2: `collections add-books` and `remove-books`**
- Test: `test_add_books_success`, `test_remove_books_success`, `test_invalid_book_id_shows_error`
- Code: variadic `BOOK_ID...` arguments

**Task 2.3: `collections ls`, `show`, `rm`, `rename`**
- Test: `test_ls_shows_collections`, `test_show_shows_books`, `test_rm_deletes`, `test_rename_success`
- Code: implement each subcommand

### Phase 3: Web UI

**Task 3.1: `/collections/` list route**
- Test: `test_collections_list_page`, `test_collections_list_htmx`
- Code: route + templates

**Task 3.2: `/collections/<id>` detail route**
- Test: `test_collection_detail_page`, `test_collection_detail_404`
- Code: route + templates showing books in collection

**Task 3.3: Collection chips on book detail**
- Test: `test_book_detail_shows_collections`
- Code: update `_detail.html` and `detail.html` to pass/show collections

## Acceptance Criteria Mapping

| Criteria | Task |
|---|---|
| Can create collection and add/remove books via CLI | 1.2, 1.4, 2.1, 2.2 |
| `show` displays current book count and list | 1.5, 2.3 |
| Web UI displays collections and membership | 3.1, 3.2, 3.3 |
| Deleting collection removes junction rows (cascade) | 1.6 (schema-level) |
| Duplicate name rejected with clear error | 1.2, 2.1 |

## TDD Exceptions

None. Every task has a well-defined behavioral boundary that can be tested before implementation. UI template layout is exercised via route-level tests (response content assertions) so there is no "pure UI layout" exception.

## Out of Scope

- Query-based / auto-updating collections
- Kobo sync
- `preview` command
- `luqum` dependency
- Collection editing (description change post-creation) — not in issue scope

## Commit Strategy

One commit per phase task (test + implementation together). Type prefix: `Add` for new features, `Test` for tests that land standalone (shouldn't happen in TDD).

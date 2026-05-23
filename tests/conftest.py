# ABOUTME: Shared pytest fixtures for Bookery tests.
# ABOUTME: Provides sample EPUB files (valid and corrupt) for testing.

from pathlib import Path

import pytest
from ebooklib import epub

# Real user paths that tests must never touch. Compared with resolved absolute
# paths so symlinks and relative segments cannot sneak past the check.
_REAL_BOOKERY_DIR = (Path.home() / ".bookery").resolve()
_REAL_LIBRARY_DB = (_REAL_BOOKERY_DIR / "library.db").resolve()
_REAL_LIBRARY_DIR = (_REAL_BOOKERY_DIR / "library").resolve()


def _is_real_user_path(path: Path) -> bool:
    """Return True if ``path`` points at the user's real catalog DB or any
    location under their real library directory.
    """
    try:
        resolved = path.expanduser().resolve()
    except (OSError, RuntimeError):
        # Unresolvable paths cannot be the real user path.
        return False
    if resolved == _REAL_LIBRARY_DB:
        return True
    try:
        resolved.relative_to(_REAL_LIBRARY_DIR)
    except ValueError:
        return False
    return True


@pytest.fixture(autouse=True, scope="session")
def _guardrail_block_real_user_paths():
    """Session-scoped guardrail: wrap ``sqlite3.connect`` so any test that
    resolves to the user's real ``~/.bookery/library.db`` or anywhere under
    ``~/.bookery/library/`` fails fast with a clear message.

    Patching at the ``sqlite3.connect`` layer (rather than only
    ``bookery.db.open_library``) catches callers that imported the helper as
    ``from bookery.db import open_library`` — those bind the original function
    object at import time, so monkeypatching the module attribute would miss
    them.

    This is best-effort: subprocesses that re-import the module do not inherit
    this monkeypatch, but the autouse env-isolation fixture already covers that
    case by pre-setting ``BOOKERY_DB`` and ``BOOKERY_LIBRARY_ROOT`` for child
    processes. Audit shows no test currently spawns the bookery CLI via
    ``subprocess`` (all ``subprocess.run`` references in ``tests/`` mock
    external binaries like ``kepubify``).

    See issue #77 (plan-05 step 5).
    """
    import sqlite3

    real_connect = sqlite3.connect

    def guarded_connect(database, *args, **kwargs):
        # ``database`` is typically a str or PathLike. In-memory dbs (":memory:")
        # and URIs are always safe — only filesystem paths can hit the user dir.
        if isinstance(database, (str, Path)) and str(database) not in {":memory:", ""}:
            candidate = Path(str(database))
            if _is_real_user_path(candidate):
                raise RuntimeError(
                    "test isolation guardrail tripped: test attempted to open "
                    f"the real user catalog path {candidate!s}. Use a "
                    "tmp_path-scoped DB instead. See CONTRIBUTING.md "
                    "'Recovering from test pollution'."
                )
        return real_connect(database, *args, **kwargs)

    sqlite3.connect = guarded_connect  # type: ignore[assignment]
    try:
        yield
    finally:
        sqlite3.connect = real_connect  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _isolate_library_root(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Point BOOKERY_LIBRARY_ROOT and BOOKERY_DB at per-test tmp paths so tests
    never touch the user's real ~/.library/ or ~/.bookery/library.db.
    """
    root = tmp_path_factory.mktemp("library_root")
    db_dir = tmp_path_factory.mktemp("library_db")
    monkeypatch.setenv("BOOKERY_LIBRARY_ROOT", str(root))
    monkeypatch.setenv("BOOKERY_DB", str(db_dir / "library.db"))
    return root


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_epub(tmp_path: Path) -> Path:
    """Create a minimal valid EPUB file with known metadata."""
    book = epub.EpubBook()

    book.set_identifier("test-isbn-978-0-123456-47-2")
    book.set_title("The Name of the Rose")
    book.set_language("en")
    book.add_author("Umberto Eco")

    book.add_metadata("DC", "publisher", "Harcourt")
    book.add_metadata("DC", "description", "A mystery set in a medieval monastery.")

    # Add a minimal chapter so the EPUB is structurally valid
    chapter = epub.EpubHtml(title="Chapter 1", file_name="chap01.xhtml", lang="en")
    chapter.content = b"<html><body><h1>Chapter 1</h1><p>Content.</p></body></html>"
    book.add_item(chapter)

    # Add navigation
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    filepath = tmp_path / "name_of_the_rose.epub"
    epub.write_epub(str(filepath), book)
    return filepath


@pytest.fixture
def corrupt_epub(tmp_path: Path) -> Path:
    """Create a corrupt file that is not a valid EPUB."""
    filepath = tmp_path / "corrupt.epub"
    filepath.write_text("this is not a valid epub file")
    return filepath


@pytest.fixture
def minimal_epub(tmp_path: Path) -> Path:
    """Create an EPUB with minimal metadata (only title)."""
    book = epub.EpubBook()
    book.set_identifier("minimal-id")
    book.set_title("Untitled Book")
    book.set_language("en")

    chapter = epub.EpubHtml(title="Content", file_name="content.xhtml", lang="en")
    chapter.content = b"<html><body><p>Minimal content.</p></body></html>"
    book.add_item(chapter)

    book.toc = [epub.Link("content.xhtml", "Content", "content")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    filepath = tmp_path / "minimal.epub"
    epub.write_epub(str(filepath), book)
    return filepath


@pytest.fixture
def calibre_tree(tmp_path: Path) -> Path:
    """Create a Calibre-style directory tree with mixed ebook formats.

    Layout:
        Calibre Library/
            Umberto Eco/
                The Name of the Rose (2739)/
                    The Name of the Rose - Umberto Eco.epub
                    The Name of the Rose - Umberto Eco.mobi
                    cover.jpg
                    metadata.opf
            Frank Herbert/
                Dune (42)/
                    Dune - Frank Herbert.mobi
                    metadata.opf
            Unknown/
                Mystery Book (99)/
                    Mystery Book - Unknown.pdf
    """
    root = tmp_path / "Calibre Library"

    # Book 1: has both EPUB and MOBI
    book1 = root / "Umberto Eco" / "The Name of the Rose (2739)"
    book1.mkdir(parents=True)
    (book1 / "The Name of the Rose - Umberto Eco.epub").write_bytes(b"fake epub")
    (book1 / "The Name of the Rose - Umberto Eco.mobi").write_bytes(b"fake mobi")
    (book1 / "cover.jpg").write_bytes(b"fake jpg")
    (book1 / "metadata.opf").write_text("<metadata/>")

    # Book 2: MOBI only (missing EPUB)
    book2 = root / "Frank Herbert" / "Dune (42)"
    book2.mkdir(parents=True)
    (book2 / "Dune - Frank Herbert.mobi").write_bytes(b"fake mobi")
    (book2 / "metadata.opf").write_text("<metadata/>")

    # Book 3: PDF only
    book3 = root / "Unknown" / "Mystery Book (99)"
    book3.mkdir(parents=True)
    (book3 / "Mystery Book - Unknown.pdf").write_bytes(b"fake pdf")

    return root

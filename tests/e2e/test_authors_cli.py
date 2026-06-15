# ABOUTME: E2E tests for the `bookery authors fix-sort` file-as backfill command.
# ABOUTME: Seeds a real catalog + EPUBs lacking file-as and drives the CLI.

from pathlib import Path

from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.formats.epub import read_creator_file_as
from bookery.metadata import BookMetadata


def _make_epub(path: Path, title: str, authors: list[str]) -> None:
    """Write a minimal EPUB whose creators carry no file-as (reproduces the bug)."""
    book = epub.EpubBook()
    book.set_identifier(f"id-{title}")
    book.set_title(title)
    book.set_language("en")
    for author in authors:
        book.add_author(author)  # no file_as -> the broken state we backfill
    chapter = epub.EpubHtml(title="c", file_name="c.xhtml", lang="en")
    chapter.content = b"<html><body><p>x</p></body></html>"
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)


def _seed(db_path: Path, title: str, authors: list[str], output: Path) -> int:
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    book_id = catalog.add_book(
        BookMetadata(title=title, authors=authors, source_path=output),
        file_hash=f"hash-{title}",
        output_path=output,
    )
    conn.close()
    return book_id


class TestAuthorsFixSort:
    def test_dry_run_lists_candidate_and_writes_nothing(self, tmp_path: Path) -> None:
        epub_path = tmp_path / "way_of_kings.epub"
        _make_epub(epub_path, "The Way of Kings", ["Sanderson, Brandon"])
        db_path = tmp_path / "lib.db"
        _seed(db_path, "The Way of Kings", ["Sanderson, Brandon"], epub_path)

        result = CliRunner().invoke(cli, ["--db", str(db_path), "authors", "fix-sort"])

        assert result.exit_code == 0, result.output
        assert "The Way of Kings" in result.output
        # Dry run must not touch the file.
        assert read_creator_file_as(epub_path) == [("Sanderson, Brandon", None)]

    def test_apply_writes_file_as_and_updates_hash(self, tmp_path: Path) -> None:
        epub_path = tmp_path / "way_of_kings.epub"
        _make_epub(epub_path, "The Way of Kings", ["Sanderson, Brandon"])
        db_path = tmp_path / "lib.db"
        book_id = _seed(
            db_path, "The Way of Kings", ["Sanderson, Brandon"], epub_path
        )

        result = CliRunner().invoke(
            cli, ["--db", str(db_path), "authors", "fix-sort", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert read_creator_file_as(epub_path) == [
            ("Sanderson, Brandon", "Sanderson, Brandon")
        ]
        conn = open_library(db_path)
        record = LibraryCatalog(conn).get_by_id(book_id)
        conn.close()
        assert record is not None
        assert record.file_hash != "hash-The Way of Kings"

    def test_apply_is_idempotent(self, tmp_path: Path) -> None:
        epub_path = tmp_path / "always.epub"
        _make_epub(epub_path, "Always Be Testing", ["Eisenberg, Bryan"])
        db_path = tmp_path / "lib.db"
        _seed(db_path, "Always Be Testing", ["Eisenberg, Bryan"], epub_path)
        runner = CliRunner()

        runner.invoke(cli, ["--db", str(db_path), "authors", "fix-sort", "--apply"])
        second = runner.invoke(
            cli, ["--db", str(db_path), "authors", "fix-sort", "--apply"]
        )

        assert second.exit_code == 0, second.output
        # Nothing left to fix on the second pass.
        assert "Always Be Testing" not in second.output
        assert read_creator_file_as(epub_path) == [
            ("Eisenberg, Bryan", "Eisenberg, Bryan")
        ]

    def test_one_failed_book_does_not_abort_the_batch(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A single book raising during apply is reported; others still process."""
        from bookery.cli.commands import authors_cmd
        from bookery.formats.epub import EpubReadError

        good = tmp_path / "good.epub"
        bad = tmp_path / "bad.epub"
        _make_epub(good, "Good Book", ["Brandon Sanderson"])
        _make_epub(bad, "Bad Book", ["Bryan Burrough"])
        db_path = tmp_path / "lib.db"
        _seed(db_path, "Bad Book", ["Bryan Burrough"], bad)
        _seed(db_path, "Good Book", ["Brandon Sanderson"], good)

        real_apply = authors_cmd._apply_fix

        def flaky(catalog, candidate):
            if candidate.record.metadata.title == "Bad Book":
                raise EpubReadError("boom")
            return real_apply(catalog, candidate)

        monkeypatch.setattr(authors_cmd, "_apply_fix", flaky)

        result = CliRunner().invoke(
            cli, ["--db", str(db_path), "authors", "fix-sort", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert "failed:" in result.output and "Bad Book" in result.output
        # The healthy book was still fixed despite the other's failure.
        assert read_creator_file_as(good) == [
            ("Brandon Sanderson", "Sanderson, Brandon")
        ]

    def test_coauthors_left_intact(self, tmp_path: Path) -> None:
        epub_path = tmp_path / "barbarians.epub"
        _make_epub(epub_path, "Barbarians", ["Bryan Burrough", "John Helyar"])
        db_path = tmp_path / "lib.db"
        _seed(db_path, "Barbarians", ["Bryan Burrough", "John Helyar"], epub_path)

        CliRunner().invoke(
            cli, ["--db", str(db_path), "authors", "fix-sort", "--apply"]
        )

        assert read_creator_file_as(epub_path) == [
            ("Bryan Burrough", "Burrough, Bryan"),
            ("John Helyar", "Helyar, John"),
        ]


def _seed_db_only(db_path: Path, title: str, authors: list[str]) -> int:
    """Seed a catalog row without an EPUB — author dedupe is DB-only (#261)."""
    conn = open_library(db_path)
    book_id = LibraryCatalog(conn).add_book(
        BookMetadata(title=title, authors=authors, source_path=Path(f"/src/{title}.epub")),
        file_hash=f"hash-{title}",
    )
    conn.close()
    return book_id


def _authors_of(db_path: Path, book_id: int) -> list[str]:
    conn = open_library(db_path)
    rec = LibraryCatalog(conn).get_by_id(book_id)
    conn.close()
    assert rec is not None
    return rec.metadata.authors


class TestAuthorsList:
    def test_duplicates_clusters_dupes_and_omits_distinct(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "lib.db"
        _seed_db_only(db_path, "Raise the Titanic", ["Cussler, Clive"])
        _seed_db_only(db_path, "Sahara", ["Clive Cussler"])
        _seed_db_only(db_path, "The Navigator", ["Dirk Cussler"])

        result = CliRunner().invoke(
            cli, ["--db", str(db_path), "authors", "list", "--duplicates"]
        )

        assert result.exit_code == 0, result.output
        assert "Cussler, Clive" in result.output
        assert "Clive Cussler" in result.output
        # A distinct author with one spelling is not a duplicate.
        assert "Dirk Cussler" not in result.output

    def test_needs_review_groups_unfixable_names(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        _seed_db_only(db_path, "MMM", ["Brooks, Jr. Frederick P."])  # credential
        _seed_db_only(db_path, "React Q", ["Mikhail Sakhniuk, Adam Boduch"])  # blob
        _seed_db_only(db_path, "Republic", ["Plato"])  # mononym
        _seed_db_only(db_path, "Elantris", ["Brandon Sanderson"])  # ok
        _seed_db_only(db_path, "Sahara", ["Cussler, Clive"])  # reorderable

        result = CliRunner().invoke(
            cli, ["--db", str(db_path), "authors", "list", "--needs-review"]
        )

        assert result.exit_code == 0, result.output
        # The three manual-merge buckets are surfaced...
        assert "Brooks, Jr. Frederick P." in result.output
        assert "Mikhail Sakhniuk, Adam Boduch" in result.output
        assert "Plato" in result.output
        # ...while clean names and auto-normalizable ones are not listed here.
        assert "Brandon Sanderson" not in result.output
        assert "Cussler, Clive" not in result.output


class TestAuthorsNormalize:
    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        book = _seed_db_only(db_path, "Raise the Titanic", ["Cussler, Clive"])
        _seed_db_only(db_path, "Sahara", ["Clive Cussler"])  # the collision twin

        result = CliRunner().invoke(cli, ["--db", str(db_path), "authors", "normalize"])

        assert result.exit_code == 0, result.output
        assert "Clive Cussler" in result.output
        assert _authors_of(db_path, book) == ["Cussler, Clive"]

    def test_apply_rewrites_collision_confirmed_and_backs_up(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "lib.db"
        book = _seed_db_only(db_path, "Raise the Titanic", ["Cussler, Clive"])
        _seed_db_only(db_path, "Sahara", ["Clive Cussler"])

        result = CliRunner().invoke(
            cli, ["--db", str(db_path), "authors", "normalize", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert _authors_of(db_path, book) == ["Clive Cussler"]
        # A timestamped backup exists and a restore command is printed.
        assert list(tmp_path.glob("lib.db.bak-*"))
        assert "Restore" in result.output or "restore" in result.output

    def test_apply_is_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        _seed_db_only(db_path, "Raise the Titanic", ["Cussler, Clive"])
        _seed_db_only(db_path, "Sahara", ["Clive Cussler"])
        runner = CliRunner()

        runner.invoke(cli, ["--db", str(db_path), "authors", "normalize", "--apply"])
        second = runner.invoke(
            cli, ["--db", str(db_path), "authors", "normalize", "--apply"]
        )

        assert second.exit_code == 0, second.output
        assert "Cussler, Clive" not in second.output

    def test_reversed_without_twin_needs_include_flag(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        # No "Brandon Sanderson" twin exists -> not collision-confirmed.
        book = _seed_db_only(db_path, "Elantris", ["Sanderson, Brandon"])

        default = CliRunner().invoke(
            cli, ["--db", str(db_path), "authors", "normalize", "--apply"]
        )
        assert _authors_of(db_path, book) == ["Sanderson, Brandon"]
        assert "Sanderson, Brandon" not in default.output

        CliRunner().invoke(
            cli,
            ["--db", str(db_path), "authors", "normalize", "--include-reversed", "--apply"],
        )
        assert _authors_of(db_path, book) == ["Brandon Sanderson"]

    def test_blob_and_credential_never_rewritten(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        blob = _seed_db_only(db_path, "React Q", ["Mikhail Sakhniuk, Adam Boduch"])
        cred = _seed_db_only(db_path, "Dog Sense", ["Patricia McConnell, Ph.D.,"])

        CliRunner().invoke(
            cli,
            ["--db", str(db_path), "authors", "normalize", "--include-reversed", "--apply"],
        )

        assert _authors_of(db_path, blob) == ["Mikhail Sakhniuk, Adam Boduch"]
        assert _authors_of(db_path, cred) == ["Patricia McConnell, Ph.D.,"]


class TestAuthorsMerge:
    def test_merge_into_canonical_with_apply(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        a = _seed_db_only(db_path, "Book A", ["Stephen King"])
        b = _seed_db_only(db_path, "Book B", ["Steven King"])

        result = CliRunner().invoke(
            cli,
            [
                "--db", str(db_path), "authors", "merge",
                "Steven King", "--into", "Stephen King", "--apply",
            ],
        )

        assert result.exit_code == 0, result.output
        assert _authors_of(db_path, a) == ["Stephen King"]
        assert _authors_of(db_path, b) == ["Stephen King"]
        assert list(tmp_path.glob("lib.db.bak-*"))

    def test_merge_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        b = _seed_db_only(db_path, "Book B", ["Steven King"])

        result = CliRunner().invoke(
            cli,
            ["--db", str(db_path), "authors", "merge", "Steven King", "--into", "Stephen King"],
        )

        assert result.exit_code == 0, result.output
        assert _authors_of(db_path, b) == ["Steven King"]

    def test_merge_prompts_for_canonical_when_into_omitted(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "lib.db"
        a = _seed_db_only(db_path, "Book A", ["Stephen King"])
        b = _seed_db_only(db_path, "Book B", ["Steven King"])

        # Pick option 1 ("Stephen King") at the prompt, then apply.
        result = CliRunner().invoke(
            cli,
            ["--db", str(db_path), "authors", "merge",
             "Stephen King", "Steven King", "--apply"],
            input="1\n",
        )

        assert result.exit_code == 0, result.output
        assert _authors_of(db_path, a) == ["Stephen King"]
        assert _authors_of(db_path, b) == ["Stephen King"]

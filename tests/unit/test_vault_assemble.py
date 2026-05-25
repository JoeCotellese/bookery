# ABOUTME: Unit tests for the vault assembler — concat + link resolution + folder grouping.
# ABOUTME: Verifies the title-slug map is built across all notes before per-note resolution.

from pathlib import Path

from bookery.core.vault.assemble import AssembledVault, assemble_vault
from bookery.core.vault.note import Note


def _note(
    title: str,
    folder: str,
    body: str,
    tags: list[str] | None = None,
    frontmatter: dict | None = None,
) -> Note:
    return Note(
        path=Path(f"{folder}/{title}.md"),
        relative_folder=folder,
        title=title,
        slug=title.lower().replace(" ", "-"),
        body=body,
        frontmatter=frontmatter or {},
        tags=tags or [],
    )


def test_assembles_concatenated_markdown_with_anchors(tmp_path: Path):
    notes = [
        _note("Note A", "Perm", "Body A linking to [[Note B]]."),
        _note("Note B", "Perm", "Body B."),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)

    assert isinstance(result, AssembledVault)
    # Folder H1 wraps letter-bucket H2 sections wrapping note H3 sections.
    assert "# Perm {#folder-perm}" in result.markdown
    assert "## N {#bucket-perm-n}" in result.markdown
    assert "### Note A {#note-a}" in result.markdown
    assert "### Note B {#note-b}" in result.markdown
    # Wiki-link resolved to the note slug.
    assert "[Note B](#note-b)" in result.markdown
    assert result.broken_link_count == 0


def test_folder_emitted_as_h1_chapter(tmp_path: Path):
    notes = [_note("Solo", "My Folder", "body")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    assert "# My Folder {#folder-my-folder}" in md
    assert "## S {#bucket-my-folder-s}" in md
    assert "### Solo {#solo}" in md
    # Folder header precedes the bucket which precedes the note section.
    assert md.index("# My Folder") < md.index("## S") < md.index("### Solo")


def test_root_folder_gets_label(tmp_path: Path):
    notes = [_note("Loose", "", "body")]
    result = assemble_vault(notes, vault_path=tmp_path)
    # Notes living at the vault root still need a chapter wrapper; use a
    # stable "Notes" label with a deterministic anchor.
    assert "# Notes {#folder-root}" in result.markdown
    assert "## L {#bucket-root-l}" in result.markdown
    assert "### Loose {#loose}" in result.markdown


def test_timestamp_prefix_stripped_for_display_and_sort(tmp_path: Path):
    # The Zettelkasten timestamp leader must not drive sort order or render
    # in the heading. The note's slug, however, must be preserved so that
    # existing wiki-link anchors keep resolving.
    n = Note(
        path=Path("202302010942 - Brand Men.md"),
        relative_folder="Perm",
        title="202302010942 - Brand Men",
        slug="202302010942-brand-men",
        body="body",
        frontmatter={},
        tags=[],
    )
    result = assemble_vault([n], vault_path=tmp_path)
    md = result.markdown
    assert "## B {#bucket-perm-b}" in md
    assert "### Brand Men {#202302010942-brand-men}" in md
    # The raw timestamped title must not appear in any heading line.
    assert "### 202302010942" not in md


def test_letter_bucket_sort_is_case_insensitive(tmp_path: Path):
    notes = [
        _note("banana", "F", "b"),
        _note("Apple", "F", "a"),
        _note("Cherry", "F", "c"),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    assert md.index("## A") < md.index("## B") < md.index("## C")
    assert md.index("### Apple") < md.index("### banana") < md.index("### Cherry")


def test_non_letter_leader_buckets_under_hash(tmp_path: Path):
    # Per the AC, notes whose stripped title starts with a digit or symbol
    # bucket under "## #" so the A-Z section stays clean.
    notes = [
        _note("42 Things", "F", "n"),
        _note("Alpha", "F", "a"),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    assert "## # {#bucket-f-hash}" in md
    assert "### 42 Things" in md
    # `#` bucket sorts before the alphabetical buckets.
    assert md.index("## #") < md.index("## A")


def test_single_note_folder_still_gets_letter_bucket(tmp_path: Path):
    notes = [_note("Onlynote", "F", "x")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    assert "## O {#bucket-f-o}" in md
    assert "### Onlynote" in md


def test_notes_alphabetized_within_folder(tmp_path: Path):
    notes = [
        _note("zeta", "F", "z"),
        _note("Alpha", "F", "a"),
        _note("mango", "F", "m"),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # Case-insensitive A→Z within a folder, now under letter buckets.
    assert md.index("### Alpha") < md.index("### mango") < md.index("### zeta")


def test_broken_link_counted(tmp_path: Path):
    notes = [_note("Solo", "P", "See [[Missing]].")]
    result = assemble_vault(notes, vault_path=tmp_path)
    assert "*Missing*" in result.markdown
    assert result.broken_link_count == 1


def test_folder_grouping_headers(tmp_path: Path):
    notes = [
        _note("A", "Perm", "a"),
        _note("B", "Lit", "b"),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # Folders are sorted; each folder H1 precedes its bucket+note sections.
    assert md.index("# Lit") < md.index("### B")
    assert md.index("# Perm") < md.index("### A")
    assert md.index("# Lit") < md.index("# Perm")


def test_index_appended_when_enabled(tmp_path: Path):
    notes = [_note("A", "P", "a", tags=["topic"])]
    result = assemble_vault(notes, vault_path=tmp_path, include_index=True)
    assert "# Tag Index" in result.markdown
    assert "## topic" in result.markdown


def test_on_progress_called_per_note(tmp_path: Path):
    notes = [_note("A", "F", "a"), _note("B", "F", "b"), _note("C", "F", "c")]
    seen: list[tuple[int, int, str]] = []

    def cb(idx: int, total: int, title: str) -> None:
        seen.append((idx, total, title))

    assemble_vault(notes, vault_path=tmp_path, on_progress=cb)

    assert [(i, t) for i, t, _ in seen] == [(1, 3), (2, 3), (3, 3)]
    assert sorted(title for _, _, title in seen) == ["A", "B", "C"]


def test_body_h1_demoted_to_h4(tmp_path: Path):
    # Folders are H1, letter buckets H2, notes H3. A body H1 must cascade to
    # H4 so pandoc's --toc-depth=3 never picks it up as a chapter or section.
    notes = [_note("Same Title", "F", "![cover](x.png)\n\n# Same Title\n\nbody\n")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # Exactly one H1 per folder.
    h1_lines = [ln for ln in md.splitlines() if ln.startswith("# ")]
    assert h1_lines == ["# F {#folder-f}"]
    # Note heading is H3; body H1 demoted to H4.
    assert "### Same Title {#same-title}" in md
    assert "#### Same Title" in md


def test_non_matching_body_h1_also_demoted(tmp_path: Path):
    notes = [_note("Title", "F", "# Different Heading\n\nbody\n")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    h1_lines = [ln for ln in md.splitlines() if ln.startswith("# ")]
    assert h1_lines == ["# F {#folder-f}"]
    assert "#### Different Heading" in md


def test_body_h2_demoted_to_h5(tmp_path: Path):
    # The letter bucket owns H2; any in-body H2 must cascade to H5 to keep
    # the TOC clean and the heading hierarchy consistent.
    notes = [_note("T", "F", "## Subsection\n\nbody\n")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # Only the bucket H2 should appear, plus any other folder buckets.
    h2_lines = [ln for ln in md.splitlines() if ln.startswith("## ")]
    assert h2_lines == ["## T {#bucket-f-t}"]
    assert "##### Subsection" in md


def test_body_h3_demoted_below_toc(tmp_path: Path):
    # Notes own H3. Any body H3 must cascade to H6 so it never appears as a
    # sibling note entry in the TOC and never causes a pandoc --split-level=3
    # spine split.
    notes = [_note("T", "F", "### Inner Heading\n\nbody\n")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    h3_lines = [ln for ln in md.splitlines() if ln.startswith("### ")]
    assert h3_lines == ["### T {#t}"]
    assert "###### Inner Heading" in md


def test_body_h4_and_h5_clamped_to_h6(tmp_path: Path):
    # H4 and H5 already sit below the TOC depth, but demote to H6 anyway so
    # every body heading lands at a single predictable level.
    notes = [_note("T", "F", "#### Four\n\n##### Five\n\nbody\n")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    assert "###### Four" in md
    assert "###### Five" in md
    # No H4 or H5 heading lines should survive.
    assert not any(ln.startswith("#### ") for ln in md.splitlines())
    assert not any(ln.startswith("##### ") for ln in md.splitlines())


def test_body_h6_left_at_h6(tmp_path: Path):
    notes = [_note("T", "F", "###### Already Deep\n\nbody\n")]
    result = assemble_vault(notes, vault_path=tmp_path)
    assert "###### Already Deep" in result.markdown


def test_literature_note_with_many_h3_subsections_yields_one_toc_entry(tmp_path: Path):
    # Real-world shape: a book note containing per-chapter H2 sections each
    # holding ### Key Points and ### Chapter Questions. None of those body
    # headings may surface at H3 or shallower in the assembled markdown.
    body = (
        "# Book Title\n\n"
        "## Chapter 1\n\n"
        "### Key Points\n- point\n\n"
        "### Chapter Questions\n1. Q?\n\n"
        "## Chapter 2\n\n"
        "### Key Points\n- point\n\n"
        "### Chapter Questions\n1. Q?\n"
    )
    notes = [_note("The Loop", "Lit", body)]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    h3_lines = [ln for ln in md.splitlines() if ln.startswith("### ")]
    # Exactly one H3 entry — the note title itself.
    assert h3_lines == ["### The Loop {#the-loop}"]


def test_duplicate_titles_in_same_folder_use_filename_hint(tmp_path: Path):
    # Two "Reference" literature notes in the same folder — common in a real
    # vault where every book note has its own References.md. The folder alone
    # cannot disambiguate them, so fall back to the filename stem.
    n1 = Note(
        path=Path("book-a-references.md"),
        relative_folder="Lit",
        title="Reference",
        slug="reference",
        body="a",
        frontmatter={},
        tags=[],
    )
    n2 = Note(
        path=Path("book-b-references.md"),
        relative_folder="Lit",
        title="Reference",
        slug="reference",
        body="b",
        frontmatter={},
        tags=[],
    )
    result = assemble_vault([n1, n2], vault_path=tmp_path)
    md = result.markdown
    assert "### Reference (book-a-references)" in md
    assert "### Reference (book-b-references)" in md


def test_duplicate_titles_get_unique_slugs(tmp_path: Path):
    # Two separate notes both titled "References" — e.g. a per-book refs note
    # repeated across many book notes in a real vault.
    notes = [
        _note("References", "Book A", "a refs"),
        _note("References", "Book B", "b refs"),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # Anchors must be unique so pandoc produces a valid EPUB.
    assert md.count("{#references}") == 1
    assert "{#references-2}" in md
    # Display titles should include a folder hint so readers can tell them apart.
    assert "References (Book A)" in md
    assert "References (Book B)" in md


def test_notes_without_tags_reported(tmp_path: Path):
    notes = [_note("Tagged", "P", "x", tags=["t"]), _note("Untagged", "P", "y")]
    result = assemble_vault(notes, vault_path=tmp_path, include_index=True)
    assert "Untagged" in result.notes_without_tags


# --- Leading-article filing (issue #175) ----------------------------------


def test_leading_the_files_under_second_word_bucket(tmp_path: Path):
    notes = [_note("The Loop", "F", "x")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # Bucket is L (from "Loop"), not T.
    assert "## L {#bucket-f-l}" in md
    assert "{#bucket-f-t}" not in md
    # Display title is unchanged.
    assert "### The Loop {#the-loop}" in md


def test_leading_a_files_under_second_word_bucket(tmp_path: Path):
    notes = [_note("A Tale of Two Cities", "F", "x")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    assert "## T {#bucket-f-t}" in md
    # No A bucket should exist (would be `## A {#bucket-f-a}`).
    assert "{#bucket-f-a}" not in md
    assert "### A Tale of Two Cities" in md


def test_leading_an_files_under_second_word_bucket(tmp_path: Path):
    # "An Owl" must file under O, not A — otherwise the test passes
    # trivially against the legacy first-letter rule.
    notes = [_note("An Owl", "F", "x")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    assert "## O {#bucket-f-o}" in md
    assert "{#bucket-f-a}" not in md
    # Display is unchanged.
    assert "### An Owl" in md


def test_leading_article_case_insensitive(tmp_path: Path):
    notes = [
        _note("THE Big One", "F", "x"),
        _note("the small one", "F", "y"),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # Both file under B and S respectively, not T.
    assert "## B {#bucket-f-b}" in md
    assert "## S {#bucket-f-s}" in md
    assert "{#bucket-f-t}" not in md


def test_word_starting_with_article_letters_not_stripped(tmp_path: Path):
    # "Theatre" must file under T — the article must be followed by a space.
    notes = [_note("Theatre", "F", "x"), _note("A.I. Risks", "F", "y")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    assert "## T {#bucket-f-t}" in md
    assert "## A {#bucket-f-a}" in md


def test_article_only_title_falls_back_to_original(tmp_path: Path):
    # Literal title "The" with no body word — must not produce an empty bucket
    # key. Fall back to the original display title so it files under T.
    notes = [_note("The", "F", "x")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    assert "## T {#bucket-f-t}" in md


def test_frontmatter_filing_title_overrides_heuristic(tmp_path: Path):
    # Author wants "The The" (a band) to actually file under T. Frontmatter
    # filing_title wins over the strip-article heuristic.
    notes = [
        _note(
            "The The",
            "F",
            "x",
            frontmatter={"filing_title": "The The"},
        ),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # filing_title "The The" still has the strip rule applied -> "The" ->
    # which is article-only, so fallback uses the filing_title as-is.
    # Net effect: files under T.
    assert "## T {#bucket-f-t}" in md


def test_frontmatter_filing_title_can_relocate_note(tmp_path: Path):
    # Author can also force a note into a different bucket via filing_title.
    notes = [
        _note(
            "The Loop",
            "F",
            "x",
            frontmatter={"filing_title": "Zebra"},
        ),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    assert "## Z {#bucket-f-z}" in md
    # Display title still reads "The Loop".
    assert "### The Loop" in md


def test_non_letter_bucket_unaffected_by_article_stripping(tmp_path: Path):
    notes = [_note("123 numbers", "F", "x")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    assert "## # {#bucket-f-hash}" in md


def test_within_bucket_sort_uses_filing_title(tmp_path: Path):
    # In the L bucket, "The Loop" should sort by "Loop", landing before
    # "Loops, Open" but after "Loop Theory".
    notes = [
        _note("Loops, Open", "F", "x"),
        _note("The Loop", "F", "y"),
        _note("Loop Theory", "F", "z"),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # Order by filing title: "Loop Theory" < "Loops, Open" < "The Loop" (filed as "Loop")
    # Actually filing keys: "loop theory", "loops, open", "loop".
    # Sorted casefold: "loop" < "loop theory" < "loops, open".
    pos_the_loop = md.index("### The Loop")
    pos_loop_theory = md.index("### Loop Theory")
    pos_loops_open = md.index("### Loops, Open")
    assert pos_the_loop < pos_loop_theory < pos_loops_open

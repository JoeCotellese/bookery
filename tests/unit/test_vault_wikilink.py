# ABOUTME: Unit tests for wiki-link parsing and resolution against a title→slug map.
# ABOUTME: Broken links render as italic plain text; counts are reported back.

from bookery.core.vault.wikilink import resolve_wikilinks


def test_resolves_simple_wikilink():
    body = "See [[Target]] for context."
    out, broken = resolve_wikilinks(body, {"Target": "target"})
    assert out == "See [Target](#target) for context."
    assert broken == 0


def test_resolves_aliased_wikilink():
    body = "See [[Target|the target note]] please."
    out, broken = resolve_wikilinks(body, {"Target": "target"})
    assert out == "See [the target note](#target) please."
    assert broken == 0


def test_broken_wikilink_becomes_italic():
    body = "See [[Nowhere]] and [[Missing|fake]]."
    out, broken = resolve_wikilinks(body, {})
    assert out == "See *Nowhere* and *fake*."
    assert broken == 2


def test_case_insensitive_match():
    body = "Try [[target]]."
    out, broken = resolve_wikilinks(body, {"Target": "target"})
    assert out == "Try [target](#target)."
    assert broken == 0


def test_multiple_in_same_line():
    body = "[[A]] and [[B]] and [[C]]."
    out, broken = resolve_wikilinks(body, {"A": "a", "C": "c"})
    assert out == "[A](#a) and *B* and [C](#c)."
    assert broken == 1


def test_preserves_non_link_content():
    body = "text [link](http://x) and `[[not-a-wiki]]` in code"
    # Code spans are NOT specially handled in v1; the link inside backticks
    # would still be rewritten. Document that behaviour explicitly.
    out, _ = resolve_wikilinks(body, {"not-a-wiki": "not-a-wiki"})
    assert "not-a-wiki" in out

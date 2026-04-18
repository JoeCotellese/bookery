# ABOUTME: Unit tests for YAML frontmatter stripping and tag extraction.
# ABOUTME: Ensures bodies are clean and tags are normalised to a flat list of strings.

from bookery.core.vault.frontmatter import parse_frontmatter


def test_no_frontmatter_returns_body_untouched():
    body, fm, tags = parse_frontmatter("# Title\n\nBody here.\n")
    assert body == "# Title\n\nBody here.\n"
    assert fm == {}
    assert tags == []


def test_yaml_frontmatter_stripped():
    src = "---\ntitle: Foo\ntags: [a, b]\n---\n# Heading\n\ncontent\n"
    body, fm, tags = parse_frontmatter(src)
    assert body == "# Heading\n\ncontent\n"
    assert fm["title"] == "Foo"
    assert tags == ["a", "b"]


def test_tags_as_space_separated_string():
    src = "---\ntags: alpha beta gamma\n---\nbody"
    _, _, tags = parse_frontmatter(src)
    assert tags == ["alpha", "beta", "gamma"]


def test_tags_single_string():
    src = "---\ntags: solo\n---\nbody"
    _, _, tags = parse_frontmatter(src)
    assert tags == ["solo"]


def test_hash_prefix_stripped_from_tags():
    src = "---\ntags: ['#foo', '#type/note']\n---\nb"
    _, _, tags = parse_frontmatter(src)
    assert tags == ["foo", "type/note"]


def test_malformed_frontmatter_treated_as_body():
    src = "---\nthis is : not : valid : yaml :::\n"
    body, fm, tags = parse_frontmatter(src)
    assert body == src
    assert fm == {}
    assert tags == []


def test_empty_frontmatter_block():
    src = "---\n---\n\nbody\n"
    body, fm, tags = parse_frontmatter(src)
    assert body == "\nbody\n"
    assert fm == {}
    assert tags == []


def test_tags_list_with_non_string_values_coerced():
    src = "---\ntags:\n  - 123\n  - ok\n---\nb"
    _, _, tags = parse_frontmatter(src)
    assert tags == ["123", "ok"]

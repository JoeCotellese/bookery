# ABOUTME: Pure author-name logic — classify a stored spelling and reorder it.
# ABOUTME: No DB. Powers the `authors` dedupe/normalize CLI (issue #261).

from __future__ import annotations

import re

# Tokens that mark a comma-separated tail as a credential/suffix rather than a
# given name, so "Patricia McConnell, Ph.D.," never reorders to a person named
# "Ph.D. Patricia McConnell". Compared case-insensitively with dots stripped.
_CREDENTIAL_TOKENS = {
    "phd",
    "md",
    "ma",
    "ba",
    "bs",
    "dphil",
    "mba",
    "jr",
    "sr",
    "ii",
    "iii",
    "iv",
    "v",
    "esq",
    "dds",
    "rn",
    "do",
}

_WS = re.compile(r"\s+")


def _norm_token(token: str) -> str:
    return token.replace(".", "").strip().lower()


def classify(name: str) -> str:
    """Bucket a stored author spelling for the dedupe/normalize pipeline.

    Returns one of:
    - ``reorderable``: a confident ``Surname, Given`` that can flip to
      ``Given Surname`` (single token before the only comma).
    - ``blob``: comma-joined full names or a compound surname we won't guess —
      routed to manual merge, never auto-rewritten.
    - ``credential``: a comma tail like ``Ph.D.`` / ``Jr.`` — never auto-rewritten.
    - ``mononym``: a single bare token (``Plato``, ``Vook``) — report only.
    - ``ok``: already ``Given Surname`` (or empty) — nothing to do.
    """
    name = name.strip()
    if not name:
        return "ok"

    if "," not in name:
        return "mononym" if len(name.split()) == 1 else "ok"

    segments = [seg.strip() for seg in name.split(",")]
    nonempty = [seg for seg in segments if seg]

    # Any credential/suffix token after the first segment disqualifies a flip.
    if any(_norm_token(seg) in _CREDENTIAL_TOKENS for seg in segments[1:]):
        return "credential"

    if len(nonempty) != 2:
        return "blob"

    left, _right = nonempty
    # Only a single-token surname before the comma is a confident Last, First.
    # Multi-token left ("Mikhail Sakhniuk, Adam Boduch", compound surnames)
    # is ambiguous — route to manual merge instead of guessing.
    return "reorderable" if len(left.split()) == 1 else "blob"


def canonical_author(name: str) -> str:
    """Return the display form: flip ``Surname, Given`` to ``Given Surname``.

    Only ``reorderable`` names change; everything else is returned stripped but
    otherwise untouched.
    """
    name = name.strip()
    if classify(name) != "reorderable":
        return name
    left, right = (seg.strip() for seg in name.split(",", 1))
    return f"{right} {left}"


def author_key(name: str) -> str:
    """Collision key grouping spellings of the *same* author.

    Built from the full canonical name (never the first name alone), so
    ``Cussler, Clive`` and ``Clive Cussler`` collide while ``Bryan Burrough``
    and ``Bryan Eisenberg`` stay distinct.
    """
    return _WS.sub(" ", canonical_author(name)).strip().lower()

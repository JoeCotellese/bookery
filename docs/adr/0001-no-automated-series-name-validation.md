# No automated series-name validation

Providers hand back series names that aren't series — the book's own title, the
author's name, a publisher or foreign-edition line. A classifier to reject them
was specified (#304) and abandoned: real one-book series and junk series have
the same shape, and no rule separates them. `Dungeon Crawler Carl: A
LitRPG/Gamelit Adventure` → `Dungeon Crawler Carl` must be kept; `Stranger In a
Strange Land - Original Uncut Version` → `Stranger in a Strange Land` must be
cleared. Both are "series is a prefix of the title"; telling them apart means
distinguishing a subtitle from an edition marker, which needs a vocabulary that
will never be complete. At this library's size (~640 books, ~45 bad rows) a
human pass is cheaper and correct, so series names are written unvalidated and
repaired by hand.

## Consequences

- `series ls` exists to make bad rows scannable, and hand edits reach the device
  through the normal `sync kobo` path (#306). That is the repair mechanism —
  there is deliberately no `series fix` command and no audit engine.
- Prevention still applies where it can be grounded in evidence rather than
  taste: #303 requires a candidate's *title* to correspond to the book before
  its series is taken, which is a fact about identity, not a judgement about
  whether a name looks like a series.
- Revisit if the library outgrows a manual scan. The index-collision signal
  sketched in #305 (a proposed position colliding with an existing member of
  the same series) is the most promising starting point, and unlike the
  name-shape rules it doesn't require guessing at English.

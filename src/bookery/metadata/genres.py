# ABOUTME: Genre normalization system for mapping freeform subjects to canonical genres.
# ABOUTME: Provides exact and regex-based matching with vote-counted primary genre selection.

import re
from collections import Counter
from dataclasses import dataclass, field

CANONICAL_GENRES: tuple[str, ...] = (
    "Literary Fiction",
    "Science Fiction",
    "Fantasy",
    "Mystery & Thriller",
    "Romance",
    "Horror",
    "Historical Fiction",
    "History & Biography",
    "Science & Technology",
    "Philosophy & Religion",
    "Self-Help & Personal Development",
    "Children's & Middle Grade",
    "Young Adult",
    "Poetry & Drama",
)

# Lowercase subject string -> canonical genre name
_SUBJECT_TO_GENRE: dict[str, str] = {
    # Literary Fiction
    "fiction": "Literary Fiction",
    "literary fiction": "Literary Fiction",
    "literature": "Literary Fiction",
    "general fiction": "Literary Fiction",
    "contemporary fiction": "Literary Fiction",
    "modern fiction": "Literary Fiction",
    "novels": "Literary Fiction",
    "short stories": "Literary Fiction",
    "satire": "Literary Fiction",
    "humorous fiction": "Literary Fiction",
    "domestic fiction": "Literary Fiction",
    "psychological fiction": "Literary Fiction",
    "american fiction": "Literary Fiction",
    "english fiction": "Literary Fiction",
    "british fiction": "Literary Fiction",
    "french fiction": "Literary Fiction",
    "italian fiction": "Literary Fiction",
    "russian fiction": "Literary Fiction",
    "german fiction": "Literary Fiction",
    # Science Fiction
    "science fiction": "Science Fiction",
    "space opera": "Science Fiction",
    "cyberpunk": "Science Fiction",
    "dystopian fiction": "Science Fiction",
    "time travel": "Science Fiction",
    "aliens": "Science Fiction",
    "robots": "Science Fiction",
    "dystopia": "Science Fiction",
    "utopias": "Science Fiction",
    "post-apocalyptic fiction": "Science Fiction",
    # Fantasy
    "fantasy": "Fantasy",
    "fantasy fiction": "Fantasy",
    "epic fantasy": "Fantasy",
    "urban fantasy": "Fantasy",
    "dark fantasy": "Fantasy",
    "fairy tales": "Fantasy",
    "mythology": "Fantasy",
    "magic": "Fantasy",
    "dragons": "Fantasy",
    "wizards": "Fantasy",
    "sword and sorcery": "Fantasy",
    # Mystery & Thriller
    "mystery": "Mystery & Thriller",
    "mystery fiction": "Mystery & Thriller",
    "detective fiction": "Mystery & Thriller",
    "detective and mystery stories": "Mystery & Thriller",
    "crime": "Mystery & Thriller",
    "crime fiction": "Mystery & Thriller",
    "thriller": "Mystery & Thriller",
    "thrillers": "Mystery & Thriller",
    "suspense": "Mystery & Thriller",
    "suspense fiction": "Mystery & Thriller",
    "espionage": "Mystery & Thriller",
    "spy fiction": "Mystery & Thriller",
    "murder": "Mystery & Thriller",
    "whodunit": "Mystery & Thriller",
    "noir": "Mystery & Thriller",
    "legal thriller": "Mystery & Thriller",
    # Romance
    "romance": "Romance",
    "romance fiction": "Romance",
    "love stories": "Romance",
    "love": "Romance",
    "romantic fiction": "Romance",
    "romantic suspense": "Romance",
    "historical romance": "Romance",
    "contemporary romance": "Romance",
    "regency romance": "Romance",
    # Horror
    "horror": "Horror",
    "horror fiction": "Horror",
    "gothic fiction": "Horror",
    "ghost stories": "Horror",
    "supernatural": "Horror",
    "vampires": "Horror",
    "zombies": "Horror",
    "haunted houses": "Horror",
    # Historical Fiction
    "historical fiction": "Historical Fiction",
    "historical novels": "Historical Fiction",
    "war fiction": "Historical Fiction",
    "war stories": "Historical Fiction",
    "world war, 1939-1945": "Historical Fiction",
    "civil war": "Historical Fiction",
    # History & Biography
    "history": "History & Biography",
    "biography": "History & Biography",
    "autobiography": "History & Biography",
    "biographies": "History & Biography",
    "memoirs": "History & Biography",
    "memoir": "History & Biography",
    "world history": "History & Biography",
    "military history": "History & Biography",
    "ancient history": "History & Biography",
    "diaries": "History & Biography",
    "letters": "History & Biography",
    "personal narratives": "History & Biography",
    # Science & Technology
    "science": "Science & Technology",
    "technology": "Science & Technology",
    "mathematics": "Science & Technology",
    "physics": "Science & Technology",
    "biology": "Science & Technology",
    "chemistry": "Science & Technology",
    "computer science": "Science & Technology",
    "programming": "Science & Technology",
    "engineering": "Science & Technology",
    "astronomy": "Science & Technology",
    "popular science": "Science & Technology",
    "natural history": "Science & Technology",
    "evolution": "Science & Technology",
    "medicine": "Science & Technology",
    # Philosophy & Religion
    "philosophy": "Philosophy & Religion",
    "religion": "Philosophy & Religion",
    "theology": "Philosophy & Religion",
    "spirituality": "Philosophy & Religion",
    "ethics": "Philosophy & Religion",
    "buddhism": "Philosophy & Religion",
    "christianity": "Philosophy & Religion",
    "islam": "Philosophy & Religion",
    "meditation": "Philosophy & Religion",
    "existentialism": "Philosophy & Religion",
    # Self-Help & Personal Development
    "self-help": "Self-Help & Personal Development",
    "personal development": "Self-Help & Personal Development",
    "psychology": "Self-Help & Personal Development",
    "motivation": "Self-Help & Personal Development",
    "productivity": "Self-Help & Personal Development",
    "mindfulness": "Self-Help & Personal Development",
    "business": "Self-Help & Personal Development",
    "leadership": "Self-Help & Personal Development",
    "finance": "Self-Help & Personal Development",
    "economics": "Self-Help & Personal Development",
    # Children's & Middle Grade
    "children's literature": "Children's & Middle Grade",
    "children's fiction": "Children's & Middle Grade",
    "juvenile fiction": "Children's & Middle Grade",
    "picture books": "Children's & Middle Grade",
    "middle grade": "Children's & Middle Grade",
    "children's stories": "Children's & Middle Grade",
    # Young Adult
    "young adult fiction": "Young Adult",
    "young adult": "Young Adult",
    "ya fiction": "Young Adult",
    "teen fiction": "Young Adult",
    "adolescence": "Young Adult",
    # Poetry & Drama
    "poetry": "Poetry & Drama",
    "poems": "Poetry & Drama",
    "drama": "Poetry & Drama",
    "plays": "Poetry & Drama",
    "theater": "Poetry & Drama",
    "theatre": "Poetry & Drama",
    "verse": "Poetry & Drama",
}

# Compiled regex patterns as fallback for subjects not in the exact map.
# Each tuple is (compiled_regex, canonical_genre).
_GENRE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sci[\-\s]?fi", re.IGNORECASE), "Science Fiction"),
    (re.compile(r"science\s+fiction", re.IGNORECASE), "Science Fiction"),
    (re.compile(r"dystopi", re.IGNORECASE), "Science Fiction"),
    (re.compile(r"detective", re.IGNORECASE), "Mystery & Thriller"),
    (re.compile(r"murder", re.IGNORECASE), "Mystery & Thriller"),
    (re.compile(r"crime|noir", re.IGNORECASE), "Mystery & Thriller"),
    (re.compile(r"suspense|thriller", re.IGNORECASE), "Mystery & Thriller"),
    (re.compile(r"spy|espionage", re.IGNORECASE), "Mystery & Thriller"),
    (re.compile(r"fantas(?:y|ies)", re.IGNORECASE), "Fantasy"),
    (re.compile(r"mytholog|fairy\s*tal", re.IGNORECASE), "Fantasy"),
    (re.compile(r"roman(?:ce|tic)", re.IGNORECASE), "Romance"),
    (re.compile(r"love\s+stor", re.IGNORECASE), "Romance"),
    (re.compile(r"horror|gothic|vampire|zombie", re.IGNORECASE), "Horror"),
    (re.compile(r"ghost\s+stor", re.IGNORECASE), "Horror"),
    (re.compile(r"histor(?:y|ical)", re.IGNORECASE), "History & Biography"),
    (re.compile(r"biograph|memoir|autobiograph", re.IGNORECASE), "History & Biography"),
    (re.compile(r"young\s+adult|ya\s+fiction|teen", re.IGNORECASE), "Young Adult"),
    (
        re.compile(r"children|juvenile|middle\s+grade|picture\s+book", re.IGNORECASE),
        "Children's & Middle Grade",
    ),
    (re.compile(r"poet(?:ry|ic)|poem|drama|play(?:s|wright)", re.IGNORECASE), "Poetry & Drama"),
    (
        re.compile(r"self[\-\s]help|personal\s+development|motivation", re.IGNORECASE),
        "Self-Help & Personal Development",
    ),
    (
        re.compile(r"philosoph|religio|theolog|spiritual", re.IGNORECASE),
        "Philosophy & Religion",
    ),
    (
        re.compile(r"science|technolog|physics|biology|chemistry|math", re.IGNORECASE),
        "Science & Technology",
    ),
]


@dataclass
class GenreMatch:
    """A single subject-to-genre match result."""

    subject: str
    genre: str
    method: str  # "exact" or "regex"


@dataclass
class GenreNormalizationResult:
    """Aggregated result of normalizing a list of subjects."""

    matches: list[GenreMatch] = field(default_factory=list)
    primary_genre: str | None = None
    unmatched: list[str] = field(default_factory=list)


def normalize_subject(subject: str) -> str | None:
    """Map a single freeform subject string to a canonical genre.

    Tries exact match first (case-insensitive), then regex patterns.
    Returns None if no match is found.
    """
    if not subject:
        return None

    key = subject.strip().lower()

    # Exact match
    genre = _SUBJECT_TO_GENRE.get(key)
    if genre is not None:
        return genre

    # Regex fallback
    for pattern, genre in _GENRE_PATTERNS:
        if pattern.search(key):
            return genre

    return None


def normalize_subjects(subjects: list[str]) -> GenreNormalizationResult:
    """Normalize a list of subjects into canonical genres with vote counting.

    Each subject is matched independently. The primary genre is the one
    with the most matches. Ties are broken by first appearance order.
    """
    matches: list[GenreMatch] = []
    unmatched: list[str] = []
    genre_order: list[str] = []  # track first-appearance order
    genre_votes: Counter[str] = Counter()

    for subject in subjects:
        key = subject.strip().lower()
        exact = _SUBJECT_TO_GENRE.get(key)
        if exact is not None:
            matches.append(GenreMatch(subject=subject, genre=exact, method="exact"))
            if exact not in genre_order:
                genre_order.append(exact)
            genre_votes[exact] += 1
            continue

        matched = False
        for pattern, genre in _GENRE_PATTERNS:
            if pattern.search(key):
                matches.append(GenreMatch(subject=subject, genre=genre, method="regex"))
                if genre not in genre_order:
                    genre_order.append(genre)
                genre_votes[genre] += 1
                matched = True
                break

        if not matched:
            unmatched.append(subject)

    # Determine primary genre: highest votes, ties broken by first appearance
    primary_genre: str | None = None
    if genre_votes:
        max_count = max(genre_votes.values())
        for genre in genre_order:
            if genre_votes[genre] == max_count:
                primary_genre = genre
                break

    return GenreNormalizationResult(
        matches=matches,
        primary_genre=primary_genre,
        unmatched=unmatched,
    )


def is_canonical_genre(name: str) -> bool:
    """Check if a genre name is in the canonical genres list (case-insensitive)."""
    return name.strip().lower() in {g.lower() for g in CANONICAL_GENRES}

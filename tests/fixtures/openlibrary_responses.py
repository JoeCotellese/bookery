# ABOUTME: Canned Open Library API response fixtures for testing.
# ABOUTME: Provides realistic JSON dicts matching OL API response shapes.

ISBN_RESPONSE = {
    "title": "The Name of the Rose",
    "authors": [{"key": "/authors/OL123A"}],
    "publishers": ["Harcourt"],
    "publish_date": "1983",
    "isbn_13": ["9780156001311"],
    "isbn_10": ["0156001314"],
    "languages": [{"key": "/languages/eng"}],
    "covers": [240727],
    "works": [{"key": "/works/OL456W"}],
}

WORKS_RESPONSE_STR_DESCRIPTION = {
    "key": "/works/OL456W",
    "title": "The Name of the Rose",
    "description": "A mystery set in a medieval Italian monastery.",
    "subjects": ["Mystery", "Historical fiction"],
}

WORKS_RESPONSE_DICT_DESCRIPTION = {
    "key": "/works/OL456W",
    "title": "The Name of the Rose",
    "description": {
        "type": "/type/text",
        "value": "A mystery set in a medieval Italian monastery.",
    },
    "subjects": ["Mystery", "Historical fiction"],
}

WORKS_RESPONSE_NO_DESCRIPTION = {
    "key": "/works/OL456W",
    "title": "The Name of the Rose",
    "subjects": ["Mystery"],
}

AUTHOR_RESPONSE = {
    "key": "/authors/OL123A",
    "name": "Umberto Eco",
    "birth_date": "5 January 1932",
    "personal_name": "Umberto Eco",
}

SEARCH_RESPONSE = {
    "numFound": 2,
    "start": 0,
    "docs": [
        {
            "key": "/works/OL456W",
            "title": "The Name of the Rose",
            "author_name": ["Umberto Eco"],
            "isbn": ["9780156001311", "0156001314"],
            "language": ["eng"],
            "publisher": ["Harcourt"],
            "cover_i": 240727,
            "first_publish_year": 1980,
        },
        {
            "key": "/works/OL789W",
            "title": "The Name of the Rose: including Postscript",
            "author_name": ["Umberto Eco"],
            "isbn": ["9780151446476"],
            "language": ["eng"],
            "publisher": ["Harcourt Brace Jovanovich"],
            "first_publish_year": 1983,
        },
    ],
}

SEARCH_RESPONSE_FOUR_DOCS = {
    "numFound": 4,
    "start": 0,
    "docs": [
        {
            "key": "/works/OL456W",
            "title": "The Name of the Rose",
            "author_name": ["Umberto Eco"],
            "isbn": ["9780156001311"],
            "language": ["eng"],
            "publisher": ["Harcourt"],
        },
        {
            "key": "/works/OL789W",
            "title": "The Name of the Rose: including Postscript",
            "author_name": ["Umberto Eco"],
            "isbn": ["9780151446476"],
            "language": ["eng"],
            "publisher": ["Harcourt Brace Jovanovich"],
        },
        {
            "key": "/works/OL101W",
            "title": "The Name of the Rose (Illustrated)",
            "author_name": ["Umberto Eco"],
            "isbn": ["9780000000003"],
            "language": ["eng"],
            "publisher": ["Penguin"],
        },
        {
            "key": "/works/OL202W",
            "title": "Name of the Rose study guide",
            "author_name": ["Someone Else"],
            "isbn": ["9780000000004"],
            "language": ["eng"],
            "publisher": ["CliffsNotes"],
        },
    ],
}

WORKS_RESPONSE_WITH_AUTHORS = {
    "key": "/works/OL456W",
    "title": "The Name of the Rose",
    "description": "A mystery set in a medieval Italian monastery.",
    "authors": [{"author": {"key": "/authors/OL123A"}, "type": {"key": "/type/author_role"}}],
    "subjects": ["Mystery", "Historical fiction"],
}

EDITION_RESPONSE = {
    "title": "The Name of the Rose",
    "authors": [{"key": "/authors/OL123A"}],
    "publishers": ["Harcourt"],
    "isbn_13": ["9780156001311"],
    "languages": [{"key": "/languages/eng"}],
    "works": [{"key": "/works/OL456W"}],
}

EDITIONS_RESPONSE = {
    "entries": [
        {
            "key": "/books/OL7914805M",
            "title": "The Alexandria Link",
            "isbn_13": ["9780739326978"],
            "publishers": ["Random House Large Print"],
            "languages": [{"key": "/languages/eng"}],
            "physical_format": "Hardcover",
            "number_of_pages": 720,
        },
        {
            "key": "/books/OL9719416M",
            "title": "The Alexandria Link",
            "isbn_13": ["9780345485755"],
            "isbn_10": ["0345485750"],
            "publishers": ["Ballantine Books"],
            "languages": [{"key": "/languages/eng"}],
            "physical_format": "Hardcover",
            "number_of_pages": 480,
        },
        {
            "key": "/books/OL9807729M",
            "title": "The Alexandria Link",
            "isbn_13": ["9780345485762"],
            "isbn_10": ["0345485769"],
            "publishers": ["Ballantine Books"],
            "languages": [{"key": "/languages/eng"}],
            "physical_format": "Mass Market Paperback",
            "number_of_pages": 512,
        },
        {
            "key": "/books/OL24270065M",
            "title": "The Alexandria Link",
            "isbn_13": ["9780345497123"],
            "publishers": ["Random House Publishing Group"],
            "languages": [{"key": "/languages/eng"}],
            "physical_format": "Electronic resource",
        },
        {
            "key": "/books/OL7915101M",
            "title": "The Alexandria Link",
            "isbn_13": ["9780739341261"],
            "publishers": ["RH Audio"],
            "languages": [{"key": "/languages/eng"}],
            "physical_format": "Audio CD",
        },
    ],
}

EDITIONS_RESPONSE_NO_ISBN = {
    "entries": [
        {
            "key": "/books/OL999M",
            "title": "Bare Bones Edition",
            "publishers": ["Some Publisher"],
        },
    ],
}

EDITIONS_RESPONSE_EMPTY = {
    "entries": [],
}

SEARCH_RESPONSE_EMPTY = {
    "numFound": 0,
    "start": 0,
    "docs": [],
}

SEARCH_RESPONSE_MINIMAL = {
    "numFound": 1,
    "start": 0,
    "docs": [
        {
            "key": "/works/OL999W",
            "title": "Minimal Book",
        },
    ],
}

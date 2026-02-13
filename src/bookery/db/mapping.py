# ABOUTME: Converts between BookMetadata dataclass and SQLite row dictionaries.
# ABOUTME: Handles JSON serialization for list/dict fields (authors, identifiers).

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bookery.metadata.types import BookMetadata


@dataclass
class BookRecord:
    """A cataloged book: BookMetadata plus database-specific fields."""

    id: int
    metadata: BookMetadata
    file_hash: str
    source_path: Path
    output_path: Path | None
    date_added: str
    date_modified: str


def metadata_to_row(
    metadata: BookMetadata,
    file_hash: str,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Convert a BookMetadata instance to a dict suitable for INSERT.

    Serializes authors as a JSON array and identifiers as a JSON object.
    Excludes cover_image (binary data stays in EPUB files, not the DB).
    """
    return {
        "title": metadata.title,
        "authors": json.dumps(metadata.authors),
        "author_sort": metadata.author_sort,
        "language": metadata.language,
        "publisher": metadata.publisher,
        "isbn": metadata.isbn,
        "description": metadata.description,
        "series": metadata.series,
        "series_index": metadata.series_index,
        "identifiers": json.dumps(metadata.identifiers),
        "source_path": str(metadata.source_path) if metadata.source_path else None,
        "output_path": str(output_path) if output_path else None,
        "file_hash": file_hash,
    }


def row_to_metadata(row: Any) -> BookMetadata:
    """Convert a database row (dict-like) back to a BookMetadata instance.

    Deserializes JSON strings for authors and identifiers fields.
    """
    source = row["source_path"]
    return BookMetadata(
        title=row["title"],
        authors=json.loads(row["authors"]) if row["authors"] else [],
        author_sort=row["author_sort"],
        language=row["language"],
        publisher=row["publisher"],
        isbn=row["isbn"],
        description=row["description"],
        series=row["series"],
        series_index=row["series_index"],
        identifiers=json.loads(row["identifiers"]) if row["identifiers"] else {},
        source_path=Path(source) if source else None,
    )


def row_to_record(row: Any) -> BookRecord:
    """Convert a full database row to a BookRecord with metadata and DB fields."""
    output = row["output_path"]
    return BookRecord(
        id=row["id"],
        metadata=row_to_metadata(row),
        file_hash=row["file_hash"],
        source_path=Path(row["source_path"]),
        output_path=Path(output) if output else None,
        date_added=row["date_added"],
        date_modified=row["date_modified"],
    )

# ABOUTME: MetadataCandidate wraps BookMetadata with match confidence and source info.
# ABOUTME: Used as the output type from metadata providers during the matching pipeline.

from dataclasses import dataclass

from bookery.metadata.types import BookMetadata


@dataclass
class MetadataCandidate:
    """A candidate metadata match from an external source.

    Wraps a BookMetadata instance with confidence score and provenance info
    so the review flow can rank and display candidates to the user.
    """

    metadata: BookMetadata
    confidence: float
    source: str
    source_id: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            msg = f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            raise ValueError(msg)

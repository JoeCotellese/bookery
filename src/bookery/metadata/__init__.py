# ABOUTME: Metadata package for ebook metadata extraction, matching, and representation.
# ABOUTME: Exports the core BookMetadata dataclass used throughout Bookery.

from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.normalizer import NormalizationResult, normalize_metadata
from bookery.metadata.provider import MetadataProvider
from bookery.metadata.types import BookMetadata

__all__ = [
    "BookMetadata",
    "MetadataCandidate",
    "MetadataProvider",
    "NormalizationResult",
    "normalize_metadata",
]

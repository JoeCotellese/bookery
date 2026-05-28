# ABOUTME: Serialize an enrich MetadataCandidate to/from a hidden Apply-form field.
# ABOUTME: Lets Apply write exactly what View previewed without re-querying the provider (#234).

import json
from dataclasses import asdict

from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata

# BookMetadata fields that can't survive a JSON round-trip and aren't needed to
# reconstruct the candidate at apply time: cover_image is re-fetched from
# cover_url, and source_path is a Path describing the original (irrelevant here).
_NON_SERIALIZABLE_FIELDS = ("cover_image", "source_path")


def serialize_candidate(candidate: MetadataCandidate) -> str:
    """Render a candidate as a compact JSON string for a hidden form field.

    The metadata is taken verbatim from the candidate (minus byte/Path fields)
    so the value Apply writes is exactly the one the diff previewed.
    """
    metadata = asdict(candidate.metadata)
    for field_name in _NON_SERIALIZABLE_FIELDS:
        metadata.pop(field_name, None)
    return json.dumps(
        {
            "confidence": candidate.confidence,
            "source": candidate.source,
            "source_id": candidate.source_id,
            "metadata": metadata,
        }
    )


def deserialize_candidate(payload: str) -> MetadataCandidate | None:
    """Rebuild a candidate from a form payload, or ``None`` on any bad input.

    Apply must never 500 on a missing, malformed, or tampered payload — it
    falls back to the re-fetch path instead. Every failure mode (invalid JSON,
    wrong shape, missing required ``title``, unknown metadata keys, out-of-range
    confidence) is funneled to ``None``.
    """
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    metadata_dict = data.get("metadata")
    if not isinstance(metadata_dict, dict):
        return None
    try:
        metadata = BookMetadata(**metadata_dict)
        return MetadataCandidate(
            metadata=metadata,
            confidence=data["confidence"],
            source=data["source"],
            source_id=data["source_id"],
        )
    except (TypeError, ValueError, KeyError):
        return None

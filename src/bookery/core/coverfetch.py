# ABOUTME: HTTP fetch for cover images referenced by a candidate's cover_url.
# ABOUTME: Best-effort and non-fatal — any failure returns None so text apply still proceeds.

import logging

import httpx

logger = logging.getLogger(__name__)

# Cover fetches are interactive (they run inline on the enrich-apply request),
# so keep the timeout short — a slow CDN should not hold up the text apply.
_COVER_FETCH_TIMEOUT = 10.0


def fetch_cover_image(
    url: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> bytes | None:
    """Download a cover image and return its bytes, or ``None`` on any failure.

    Failure is deliberately non-fatal: a blank URL, network error, non-200
    response, non-image content-type, or empty body all return ``None`` with a
    logged warning. The caller (enrich-apply) treats ``None`` as "no cover this
    time" and still applies the candidate's text metadata.

    Args:
        url: The candidate's ``cover_url``. Empty/whitespace short-circuits.
        transport: Optional httpx transport for test injection.

    Returns:
        The downloaded image bytes, or ``None`` if the cover could not be fetched.
    """
    if not url or not url.strip():
        return None

    client_kwargs: dict[str, object] = {
        "headers": {"User-Agent": "bookery/0.1.0"},
        "timeout": _COVER_FETCH_TIMEOUT,
        "follow_redirects": True,
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    try:
        with httpx.Client(**client_kwargs) as client:  # type: ignore[arg-type]
            response = client.get(url)
    except httpx.HTTPError as exc:
        logger.warning("Cover fetch failed for %s: %s", url, exc)
        return None

    if response.status_code != 200:
        logger.warning("Cover fetch got HTTP %d for %s", response.status_code, url)
        return None

    content_type = response.headers.get("Content-Type", "")
    if not content_type.lower().startswith("image/"):
        logger.warning("Cover fetch got non-image content-type %r for %s", content_type, url)
        return None

    data = response.content
    if not data:
        logger.warning("Cover fetch returned empty body for %s", url)
        return None

    return data

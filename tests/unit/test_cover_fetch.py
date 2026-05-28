# ABOUTME: Unit tests for the cover-image HTTP fetch helper used by enrich-apply.
# ABOUTME: Verifies bytes are returned on success and None (non-fatal) on every failure mode.

import httpx

from bookery.core.coverfetch import fetch_cover_image


class _Transport(httpx.BaseTransport):
    """Canned-response transport for the cover fetch helper."""

    def __init__(
        self,
        response: httpx.Response | None = None,
        *,
        raise_exc: Exception | None = None,
    ) -> None:
        self._response = response
        self._raise_exc = raise_exc
        self.requested_urls: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requested_urls.append(str(request.url))
        if self._raise_exc is not None:
            raise self._raise_exc
        assert self._response is not None
        return self._response


_JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-cover-bytes" * 4


class TestFetchCoverImage:
    def test_returns_bytes_on_200_image(self) -> None:
        transport = _Transport(
            httpx.Response(200, content=_JPEG, headers={"Content-Type": "image/jpeg"})
        )
        data = fetch_cover_image("https://example/cover.jpg", transport=transport)
        assert data == _JPEG
        assert transport.requested_urls == ["https://example/cover.jpg"]

    def test_returns_none_on_non_200(self) -> None:
        transport = _Transport(httpx.Response(404, content=b"missing"))
        assert fetch_cover_image("https://example/cover.jpg", transport=transport) is None

    def test_returns_none_on_non_image_content_type(self) -> None:
        transport = _Transport(
            httpx.Response(
                200, content=b"<html>nope</html>", headers={"Content-Type": "text/html"}
            )
        )
        assert fetch_cover_image("https://example/cover.jpg", transport=transport) is None

    def test_returns_none_on_empty_body(self) -> None:
        transport = _Transport(
            httpx.Response(200, content=b"", headers={"Content-Type": "image/jpeg"})
        )
        assert fetch_cover_image("https://example/cover.jpg", transport=transport) is None

    def test_returns_none_on_network_error(self) -> None:
        transport = _Transport(raise_exc=httpx.ConnectError("boom"))
        assert fetch_cover_image("https://example/cover.jpg", transport=transport) is None

    def test_returns_none_on_blank_url(self) -> None:
        # No network call should be attempted for an empty URL.
        transport = _Transport()
        assert fetch_cover_image("", transport=transport) is None
        assert transport.requested_urls == []

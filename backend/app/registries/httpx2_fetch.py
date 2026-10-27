"""``Fetch`` on the httpx2 client: the only registries module that imports a networking library.

Temporary: when this branch is rebased on #15, this adapter is replaced by the application's
guarded outbound client (``app.http_client``), and this file is deleted.
"""

from collections.abc import Mapping

import httpx2

from app.registries.http import FetchedResponse, FetchError


class Httpx2Fetch:
    def __init__(
        self, timeout_seconds: float, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        self._client = httpx2.AsyncClient(
            timeout=httpx2.Timeout(timeout_seconds), transport=transport, follow_redirects=False
        )

    async def __call__(
        self, url: str, params: Mapping[str, str], headers: Mapping[str, str]
    ) -> FetchedResponse:
        try:
            response = await self._client.get(url, params=dict(params), headers=dict(headers))
        except httpx2.TimeoutException as error:
            raise FetchError("timeout") from error
        except httpx2.HTTPError as error:
            raise FetchError("unreachable") from error
        return FetchedResponse(
            status_code=response.status_code,
            body=response.content,
            headers={name.lower(): value for name, value in response.headers.items()},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

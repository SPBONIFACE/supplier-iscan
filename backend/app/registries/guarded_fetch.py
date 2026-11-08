"""``Fetch`` on the guarded client of #15: the registries' only way out to the network.

The guarded client is synchronous; each request runs in a worker thread so that the registries'
asynchronous interface (parallel Wikidata and GLEIF searches) is not blocked. The registries' hosts
are public, so the guard (address vetting, checked redirects, total deadline) applies as for any
other outbound fetch. This module imports no networking library.
"""

import asyncio
from collections.abc import Mapping
from urllib.parse import urlencode

from app.http_client import NETWORK_ERRORS, FetchError, FetchTimeoutError, GuardedClient
from app.registries.http import FetchedResponse
from app.registries.http import FetchError as RegistryFetchError


def _with_params(url: str, params: Mapping[str, str]) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return url + separator + urlencode(dict(params))


class GuardedFetch:
    def __init__(self, client: GuardedClient, timeout_seconds: float) -> None:
        self._client = client
        self._timeout = timeout_seconds

    def _get(self, url: str, headers: Mapping[str, str]) -> FetchedResponse:
        try:
            response = self._client.get(url, timeout=self._timeout, headers=headers)
        except FetchTimeoutError as error:
            raise RegistryFetchError("timeout") from error
        except FetchError as error:
            raise RegistryFetchError("unreachable") from error
        except NETWORK_ERRORS as error:
            # The library's timeout classes are all named "...Timeout".
            if type(error).__name__.endswith("Timeout"):
                raise RegistryFetchError("timeout") from error
            raise RegistryFetchError("unreachable") from error
        return FetchedResponse(
            status_code=response.status_code,
            body=response.content,
            headers={name.lower(): value for name, value in response.headers.items()},
        )

    async def __call__(
        self, url: str, params: Mapping[str, str], headers: Mapping[str, str]
    ) -> FetchedResponse:
        return await asyncio.to_thread(self._get, _with_params(url, params), dict(headers))

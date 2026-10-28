"""Perplexity, through the official `perplexityai` SDK (chat completions).

- Structuring: `response_format` with a JSON schema and `disable_search=True` (only the data
  given is used); the JSON answer is returned for validation.
- Retrieval: a search-backed completion; URLs come from the typed `search_results` (URL, title,
  snippet), or from the typed `citations` list when there are no search results. The answer text
  is ignored.

The client gets the key and the endpoint explicitly and `max_retries=0` (#12 meters each attempt).
"""

from typing import Any

import perplexity

from app.providers.adapters.common import TIMEOUT_SECONDS
from app.providers.catalogue import ProviderConfigSpec
from app.providers.interface import RetrievalRequest, RetrievedUrl, StructuringRequest


def make_client(
    config: ProviderConfigSpec, api_key: str, http_client: Any = None
) -> perplexity.Perplexity:
    """`http_client` is for tests only (a mock transport); production passes none."""
    return perplexity.Perplexity(
        api_key=api_key,
        base_url=config.endpoint,
        max_retries=0,
        timeout=TIMEOUT_SECONDS,
        http_client=http_client,
    )


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(getattr(chunk, "text", "") or "" for chunk in content)
    return ""


class PerplexityStructuring:
    def __init__(self, config: ProviderConfigSpec, client: perplexity.Perplexity) -> None:
        self._config = config
        self._client = client

    def generate_json(
        self, request: StructuringRequest, schema_name: str, json_schema: dict[str, object]
    ) -> str:
        completion = self._client.chat.completions.create(
            model=self._config.model_id,
            messages=[
                {"role": "system", "content": request.instructions},
                {"role": "user", "content": request.data},
            ],
            max_tokens=request.max_output_tokens,
            disable_search=True,
            stream=False,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": json_schema},
            },
        )
        choices = getattr(completion, "choices", None) or []
        return _text(choices[0].message.content) if choices else ""


class PerplexityRetrieval:
    def __init__(self, config: ProviderConfigSpec, client: perplexity.Perplexity) -> None:
        self._config = config
        self._client = client

    def search(self, request: RetrievalRequest) -> list[RetrievedUrl]:
        completion = self._client.chat.completions.create(
            model=self._config.model_id,
            messages=[
                {"role": "system", "content": request.instructions},
                {"role": "user", "content": request.query},
            ],
            stream=False,
        )
        results = getattr(completion, "search_results", None) or []
        if results:
            return [
                RetrievedUrl(url=result.url, snippet=result.snippet or result.title or "")
                for result in results
            ]
        return [RetrievedUrl(url=url) for url in getattr(completion, "citations", None) or []]


def build_structuring(config: ProviderConfigSpec, api_key: str) -> PerplexityStructuring:
    return PerplexityStructuring(config, make_client(config, api_key))


def build_retrieval(config: ProviderConfigSpec, api_key: str) -> PerplexityRetrieval:
    return PerplexityRetrieval(config, make_client(config, api_key))

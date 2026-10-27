"""OpenAI, through the official `openai` SDK (Responses API).

- Structuring: `text.format` with a JSON schema; the JSON output text is returned for validation.
- Retrieval: the `web_search` tool; URLs come from the typed `url_citation` annotations.

Every call sets `store=False`, so the response is not kept for later retrieval through the API.
The client gets the key and the endpoint explicitly and `max_retries=0` (#12 meters each attempt).
"""

from typing import Any

import openai

from app.providers.adapters.common import TIMEOUT_SECONDS
from app.providers.catalogue import ProviderConfigSpec
from app.providers.interface import RetrievalRequest, RetrievedUrl, StructuringRequest


def make_client(config: ProviderConfigSpec, api_key: str, http_client: Any = None) -> openai.OpenAI:
    """`http_client` is for tests only (a mock transport); production passes none."""
    return openai.OpenAI(
        api_key=api_key,
        base_url=config.endpoint,
        max_retries=0,
        timeout=TIMEOUT_SECONDS,
        http_client=http_client,
    )


class OpenAIStructuring:
    def __init__(self, config: ProviderConfigSpec, client: openai.OpenAI) -> None:
        self._config = config
        self._client = client

    def generate_json(
        self, request: StructuringRequest, schema_name: str, json_schema: dict[str, object]
    ) -> str:
        response = self._client.responses.create(
            model=self._config.model_id,
            instructions=request.instructions,
            input=request.data,
            max_output_tokens=request.max_output_tokens,
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": json_schema,
                    "strict": False,
                }
            },
        )
        return response.output_text


class OpenAIRetrieval:
    def __init__(self, config: ProviderConfigSpec, client: openai.OpenAI) -> None:
        self._config = config
        self._client = client

    def search(self, request: RetrievalRequest) -> list[RetrievedUrl]:
        response = self._client.responses.create(
            model=self._config.model_id,
            instructions=request.instructions,
            input=request.query,
            store=False,
            tools=[{"type": "web_search"}],
        )
        urls: list[RetrievedUrl] = []
        for item in response.output:
            if item.type != "message":
                continue
            for content in item.content:
                if content.type != "output_text":
                    continue
                for annotation in content.annotations:
                    if annotation.type == "url_citation":
                        urls.append(RetrievedUrl(url=annotation.url, snippet=annotation.title))
        return urls


def structuring(config: ProviderConfigSpec, api_key: str) -> OpenAIStructuring:
    return OpenAIStructuring(config, make_client(config, api_key))


def retrieval(config: ProviderConfigSpec, api_key: str) -> OpenAIRetrieval:
    return OpenAIRetrieval(config, make_client(config, api_key))

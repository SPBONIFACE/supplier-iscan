"""Gemini, through the official `google-genai` SDK (Gemini Developer API, `generate_content`).

- Structuring: `response_mime_type="application/json"` with `response_json_schema` (the model is
  constrained to the schema); the JSON text is returned for validation.
- Retrieval: the `google_search` tool; URLs come from the typed `grounding_metadata` of the
  candidates, never from the answer text.

The client is built with the configuration's endpoint as base URL, no SDK retry (#12 meters each
attempt) and `vertexai=False`, so no environment variable can switch it to another backend.
"""

from typing import Any

from google import genai
from google.genai import types

from app.providers.adapters.common import TIMEOUT_SECONDS
from app.providers.catalogue import ProviderConfigSpec
from app.providers.interface import RetrievalRequest, RetrievedUrl, StructuringRequest


def make_client(config: ProviderConfigSpec, api_key: str, http_client: Any = None) -> genai.Client:
    """`http_client` is for tests only (a mock transport); production passes none."""
    return genai.Client(
        vertexai=False,
        api_key=api_key,
        http_options=types.HttpOptions(
            base_url=config.endpoint,
            timeout=TIMEOUT_SECONDS * 1000,
            retry_options=types.HttpRetryOptions(attempts=1),
            httpx_client=http_client,
        ),
    )


class GeminiStructuring:
    def __init__(self, config: ProviderConfigSpec, client: genai.Client) -> None:
        self._config = config
        self._client = client

    def generate_json(
        self, request: StructuringRequest, schema_name: str, json_schema: dict[str, object]
    ) -> str:
        response = self._client.models.generate_content(
            model=self._config.model_id,
            contents=request.data,
            config=types.GenerateContentConfig(
                system_instruction=request.instructions,
                response_mime_type="application/json",
                response_json_schema=json_schema,
                max_output_tokens=request.max_output_tokens,
            ),
        )
        return response.text or ""


class GeminiRetrieval:
    def __init__(self, config: ProviderConfigSpec, client: genai.Client) -> None:
        self._config = config
        self._client = client

    def search(self, request: RetrievalRequest) -> list[RetrievedUrl]:
        response = self._client.models.generate_content(
            model=self._config.model_id,
            contents=request.query,
            config=types.GenerateContentConfig(
                system_instruction=request.instructions,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        urls: list[RetrievedUrl] = []
        for candidate in response.candidates or []:
            metadata = candidate.grounding_metadata
            for chunk in (metadata.grounding_chunks if metadata else None) or []:
                if chunk.web and chunk.web.uri:
                    urls.append(RetrievedUrl(url=chunk.web.uri, snippet=chunk.web.title or ""))
        return urls


def structuring(config: ProviderConfigSpec, api_key: str) -> GeminiStructuring:
    return GeminiStructuring(config, make_client(config, api_key))


def retrieval(config: ProviderConfigSpec, api_key: str) -> GeminiRetrieval:
    return GeminiRetrieval(config, make_client(config, api_key))

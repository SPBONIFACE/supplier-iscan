"""Claude, through the official `anthropic` SDK (Messages API).

- Structuring: `output_config.format` with a JSON schema (structured outputs, documented at
  https://platform.claude.com/docs/en/build-with-claude/structured-outputs); the JSON text of the
  answer is returned for validation. The API accepts only a subset of JSON Schema (no
  `minLength`/`maxLength`, `minimum`/`maximum`, `maxItems`, `minItems` above 1; every object needs
  `additionalProperties: false`; other keywords are a 400). `api_schema` converts the app's schema
  with the SDK's own `transform_schema`, which drops what the API refuses and moves it into the
  field description. Only the request is simplified: the app still validates the answer fully
  (#125).
- Retrieval: the server-side `web_search` tool; URLs come from the typed citations of the answer
  (with the cited source text as snippet) and from the typed search-result blocks, never from the
  answer text.

The client gets the key and the endpoint explicitly (so no environment variable or profile file is
consulted for them) and `max_retries=0` (#12 meters each attempt).
"""

from typing import Any

import anthropic

from app.providers.adapters.common import TIMEOUT_SECONDS
from app.providers.catalogue import ProviderConfigSpec
from app.providers.interface import (
    RetrievalOutput,
    RetrievalRequest,
    RetrievedUrl,
    StructuringOutput,
    StructuringRequest,
)
from app.providers.metering import NO_USAGE, CallUsage

RETRIEVAL_MAX_TOKENS = 2048
WEB_SEARCH_MAX_USES = 5


def make_client(
    config: ProviderConfigSpec, api_key: str, http_client: Any = None
) -> anthropic.Anthropic:
    """`http_client` is for tests only (a mock transport); production passes none."""
    return anthropic.Anthropic(
        api_key=api_key,
        base_url=config.endpoint,
        max_retries=0,
        timeout=TIMEOUT_SECONDS,
        http_client=http_client,
    )


def api_schema(json_schema: dict[str, object]) -> dict[str, Any]:
    """The app's JSON schema in the subset Anthropic's structured outputs accept (#125)."""
    return anthropic.transform_schema(json_schema)


def _usage(message: Any) -> CallUsage:
    """Input includes cache reads and writes; web searches are the billed tool calls."""
    usage = message.usage
    if usage is None:
        return NO_USAGE
    server_tools = getattr(usage, "server_tool_use", None)
    return CallUsage(
        input_tokens=(usage.input_tokens or 0)
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        + (getattr(usage, "cache_read_input_tokens", 0) or 0),
        output_tokens=usage.output_tokens or 0,
        tool_calls=(server_tools.web_search_requests if server_tools else 0) or 0,
    )


class ClaudeStructuring:
    def __init__(self, config: ProviderConfigSpec, client: anthropic.Anthropic) -> None:
        self._config = config
        self._client = client

    def generate_json(
        self, request: StructuringRequest, schema_name: str, json_schema: dict[str, object]
    ) -> StructuringOutput:
        message = self._client.messages.create(
            model=self._config.model_id,
            max_tokens=request.max_output_tokens,
            system=request.instructions,
            messages=[{"role": "user", "content": request.data.text}],
            output_config={"format": {"type": "json_schema", "schema": api_schema(json_schema)}},
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        return StructuringOutput(text, _usage(message))


class ClaudeRetrieval:
    def __init__(self, config: ProviderConfigSpec, client: anthropic.Anthropic) -> None:
        self._config = config
        self._client = client

    def search(self, request: RetrievalRequest) -> RetrievalOutput:
        message = self._client.messages.create(
            model=self._config.model_id,
            max_tokens=RETRIEVAL_MAX_TOKENS,
            system=request.instructions,
            messages=[{"role": "user", "content": request.query.text}],
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": WEB_SEARCH_MAX_USES,
                }
            ],
        )
        cited: list[RetrievedUrl] = []
        found: list[RetrievedUrl] = []
        for block in message.content:
            if block.type == "text":
                for citation in block.citations or []:
                    if citation.type == "web_search_result_location":
                        cited.append(RetrievedUrl(url=citation.url, snippet=citation.cited_text))
            elif block.type == "web_search_tool_result" and isinstance(block.content, list):
                found.extend(
                    RetrievedUrl(url=result.url, snippet=result.title) for result in block.content
                )
        # Cited URLs first: their snippet is the source's own text.
        return RetrievalOutput(cited + found, _usage(message))


def build_structuring(config: ProviderConfigSpec, api_key: str) -> ClaudeStructuring:
    return ClaudeStructuring(config, make_client(config, api_key))


def build_retrieval(config: ProviderConfigSpec, api_key: str) -> ClaudeRetrieval:
    return ClaudeRetrieval(config, make_client(config, api_key))

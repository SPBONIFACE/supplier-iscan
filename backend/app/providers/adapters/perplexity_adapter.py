"""Perplexity, through the official `perplexityai` SDK, on the Agent API (`responses.create`).

Sonar Chat Completions ended on 27 Sep 2026; this is the migration of
https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/overview. The model is given as
`provider/model` (`perplexity/sonar`, the Agent API's name for Sonar), set in the configuration's
`model_id`.

- Structuring: `response_format` with a JSON schema and no tool (so nothing is searched: only the
  data given is used); the JSON answer (`output_text`) is returned for validation.
- Retrieval: the `web_search` tool; URLs come from the typed `search_results` output items (URL,
  title, snippet), or, when there are none, from the typed annotations of the answer. The answer
  text is ignored. The loop is bounded by `max_steps`.
- Metering: the amount Perplexity bills (`usage.cost.total_cost`, tokens and tool calls
  included) is the cost of the call; tool calls are counted from `usage.tool_calls_details`.

The client gets the key and the endpoint explicitly and `max_retries=0` (#12 meters each attempt).
"""

from decimal import Decimal
from typing import Any

import perplexity

from app.providers.adapters.common import TIMEOUT_SECONDS
from app.providers.catalogue import ProviderConfigSpec
from app.providers.interface import (
    RETRIEVAL_MAX_OUTPUT_TOKENS,
    RETRIEVAL_MAX_TOOL_CALLS,
    RetrievalOutput,
    RetrievalRequest,
    RetrievedUrl,
    StructuringOutput,
    StructuringRequest,
)
from app.providers.metering import NO_USAGE, CallUsage


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


def _usage(response: object) -> CallUsage:
    """Perplexity reports the amount it billed (USD): that amount is the cost of the call."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return NO_USAGE
    cost = getattr(usage, "cost", None)
    total = getattr(cost, "total_cost", None)
    details = getattr(usage, "tool_calls_details", None) or {}
    return CallUsage(
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        tool_calls=sum(getattr(detail, "invocation", 0) or 0 for detail in details.values()),
        billed_amount=Decimal(str(total)) if total is not None else None,
        billed_currency=getattr(cost, "currency", "USD") if total is not None else None,
    )


def _output(response: object) -> list[Any]:
    return list(getattr(response, "output", None) or [])


class PerplexityStructuring:
    def __init__(self, config: ProviderConfigSpec, client: perplexity.Perplexity) -> None:
        self._config = config
        self._client = client

    def generate_json(
        self, request: StructuringRequest, schema_name: str, json_schema: dict[str, object]
    ) -> StructuringOutput:
        response = self._client.responses.create(
            model=self._config.model_id,
            instructions=request.instructions,
            input=request.data.text,
            max_output_tokens=request.max_output_tokens,
            store=False,
            stream=False,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": json_schema},
            },
        )
        return StructuringOutput(response.output_text, _usage(response))


class PerplexityRetrieval:
    def __init__(self, config: ProviderConfigSpec, client: perplexity.Perplexity) -> None:
        self._config = config
        self._client = client

    def search(self, request: RetrievalRequest) -> RetrievalOutput:
        response = self._client.responses.create(
            model=self._config.model_id,
            instructions=request.instructions,
            input=request.query.text,
            max_output_tokens=RETRIEVAL_MAX_OUTPUT_TOKENS,
            max_steps=RETRIEVAL_MAX_TOOL_CALLS,
            store=False,
            stream=False,
            tools=[{"type": "web_search"}],
        )
        usage = _usage(response)
        found = [
            RetrievedUrl(url=result.url, snippet=result.snippet or result.title or "")
            for item in _output(response)
            if item.type == "search_results"
            for result in item.results
        ]
        if found:
            return RetrievalOutput(found, usage)
        cited = [
            RetrievedUrl(url=annotation.url, snippet=annotation.title or "")
            for item in _output(response)
            if item.type == "message"
            for content in item.content or []
            for annotation in content.annotations or []
            if annotation.url
        ]
        return RetrievalOutput(cited, usage)


def build_structuring(config: ProviderConfigSpec, api_key: str) -> PerplexityStructuring:
    return PerplexityStructuring(config, make_client(config, api_key))


def build_retrieval(config: ProviderConfigSpec, api_key: str) -> PerplexityRetrieval:
    return PerplexityRetrieval(config, make_client(config, api_key))

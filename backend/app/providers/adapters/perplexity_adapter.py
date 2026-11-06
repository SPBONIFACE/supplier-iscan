"""Perplexity, through the official `perplexityai` SDK, on the Agent API (`responses.create`).

Sonar Chat Completions ended on 27 Sep 2026; this is the migration of
https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/overview. The model is given as
`provider/model` (`perplexity/sonar`, the Agent API's name for Sonar), set in the configuration's
`model_id`.

- Structuring: `response_format` with a JSON schema and no tool (so nothing is searched: only the
  data given is used); the JSON answer (`output_text`) is returned for validation. The docs say a
  declared property that is not in `required` may come back as JSON null: such nulls are removed
  first, so the schema's own default applies.
- Retrieval: the `web_search` tool; URLs come from the typed `search_results` output items (URL,
  title, snippet), or, when there are none, from the typed annotations of the answer. The answer
  text is ignored. The loop is bounded by `max_steps`. Every field of an entry is treated as
  optional: an entry without a usable URL is skipped and a long snippet is cut (it only ranks),
  so one odd entry never fails the response (#122).
- Metering: the amount Perplexity bills (`usage.cost.total_cost`, tokens and tool calls
  included) is the cost of the call; tool calls are counted from `usage.tool_calls_details`.
- Diagnostic: with `PROVIDER_SHAPE_DIAGNOSTIC=1` the shape of each response (names and types, no
  text) is written to a local file (`app.providers.shape`).

The client gets the key and the endpoint explicitly and `max_retries=0` (#12 meters each attempt).
"""

import json
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
from app.providers.shape import write_shape

# The bounds of `RetrievedUrl`.
URL_MAX_LENGTH = 4096
SNIPPET_MAX_LENGTH = 4000


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


def _field(item: object, name: str) -> Any:
    """A field of a typed item, or of a plain dict when the SDK left an item untyped."""
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _number(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _usage(response: object) -> CallUsage:
    """Perplexity reports the amount it billed (USD): that amount is the cost of the call."""
    usage = _field(response, "usage")
    if usage is None:
        return NO_USAGE
    cost = _field(usage, "cost")
    total = _field(cost, "total_cost")
    details = _field(usage, "tool_calls_details")
    calls = (
        sum(_number(_field(detail, "invocation")) for detail in details.values())
        if (isinstance(details, dict))
        else 0
    )
    return CallUsage(
        input_tokens=_number(_field(usage, "input_tokens")),
        output_tokens=_number(_field(usage, "output_tokens")),
        tool_calls=calls,
        billed_amount=Decimal(str(total)) if isinstance(total, int | float | str) else None,
        billed_currency=(_field(cost, "currency") or "USD")
        if isinstance(total, int | float | str)
        else None,
    )


def _output(response: object) -> list[Any]:
    output = _field(response, "output")
    return list(output) if isinstance(output, list) else []


def _retrieved(url: object, *texts: object) -> RetrievedUrl | None:
    """One address with its ranking snippet, or None when the entry cannot be used."""
    if not isinstance(url, str) or not url or len(url) > URL_MAX_LENGTH:
        return None
    snippet = next((text for text in texts if isinstance(text, str) and text), "")
    return RetrievedUrl(url=url, snippet=snippet[:SNIPPET_MAX_LENGTH])


def _drop_unrequired_nulls(value: Any, schema: Any, definitions: dict[str, Any]) -> Any:
    """Remove JSON nulls of declared properties that are not in `required` (docs, Structured
    Outputs: such a property "may resolve to JSON null"); the schema's own default then applies."""
    if isinstance(schema, dict) and "$ref" in schema:
        schema = definitions.get(str(schema["$ref"]).rsplit("/", 1)[-1], {})
    if not isinstance(schema, dict):
        return value
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        return {
            key: _drop_unrequired_nulls(item, properties.get(key), definitions)
            for key, item in value.items()
            if not (item is None and key in properties and key not in required)
        }
    if isinstance(value, list):
        return [_drop_unrequired_nulls(item, schema.get("items"), definitions) for item in value]
    return value


def _structured_text(text: str, json_schema: dict[str, object]) -> str:
    """The answer text without unrequired nulls; unchanged when it is not a JSON object (the
    client then rejects it against the schema, as for any other provider)."""
    try:
        document = json.loads(text)
    except ValueError:
        return text
    if not isinstance(document, dict):
        return text
    definitions = json_schema.get("$defs")
    cleaned = _drop_unrequired_nulls(
        document, json_schema, definitions if isinstance(definitions, dict) else {}
    )
    return json.dumps(cleaned)


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
        write_shape("perplexity", "structuring", response)
        text = response.output_text
        return StructuringOutput(
            _structured_text(text if isinstance(text, str) else "", json_schema), _usage(response)
        )


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
        write_shape("perplexity", "retrieval", response)
        usage = _usage(response)
        output = _output(response)
        found = [
            entry
            for item in output
            if _field(item, "type") == "search_results"
            for result in _field(item, "results") or []
            if (
                entry := _retrieved(
                    _field(result, "url"), _field(result, "snippet"), _field(result, "title")
                )
            )
        ]
        if found:
            return RetrievalOutput(found, usage)
        cited = [
            entry
            for item in output
            if _field(item, "type") == "message"
            for content in _field(item, "content") or []
            for annotation in _field(content, "annotations") or []
            if (entry := _retrieved(_field(annotation, "url"), _field(annotation, "title")))
        ]
        return RetrievalOutput(cited, usage)


def build_structuring(config: ProviderConfigSpec, api_key: str) -> PerplexityStructuring:
    return PerplexityStructuring(config, make_client(config, api_key))


def build_retrieval(config: ProviderConfigSpec, api_key: str) -> PerplexityRetrieval:
    return PerplexityRetrieval(config, make_client(config, api_key))

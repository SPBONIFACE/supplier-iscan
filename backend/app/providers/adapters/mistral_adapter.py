"""Mistral, through the official `mistralai` SDK.

- Structuring (`chat_completions`): `response_format` with a JSON schema; the JSON answer is
  returned for validation.
- Retrieval (`conversations`): the Conversations API with the `web_search` tool and `store=False`;
  URLs come from the typed `tool_reference` chunks of the output, never from the answer text.

The SDK ships its own OpenTelemetry tracing hook. It records request and response content in its
spans (the GenAI input and output messages) when an OpenTelemetry tracer provider is configured,
and can export them to Mistral when MISTRAL_SDK_TELEMETRY is set. Prompts and responses must never
reach telemetry (spec, Non-functional: no personal data in telemetry; #51), so `make_client`
removes that hook from the client: the SDK then creates no span and exports nothing. Its debug
logger is replaced by a disabled one (MISTRAL_DEBUG would otherwise log requests). No SDK retry
(#12 meters each attempt).
"""

import logging
from typing import Any

from mistralai.client import Mistral
from mistralai.client._hooks.tracing import TracingHook
from mistralai.client.models import (
    JSONSchema,
    ResponseFormat,
    SystemMessage,
    UserMessage,
    WebSearchTool,
)
from mistralai.client.utils import BackoffStrategy, RetryConfig

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

_HOOK_LISTS = ("before_request_hooks", "after_success_hooks", "after_error_hooks")
_NO_RETRY = RetryConfig("none", BackoffStrategy(0, 0, 1.0, 0), retry_connection_errors=False)

_silent_logger = logging.getLogger("app.providers.mistral_sdk")
_silent_logger.disabled = True


def remove_tracing(client: Mistral) -> None:
    hooks = client.sdk_configuration.__dict__["_hooks"]
    for name in _HOOK_LISTS:
        kept = [hook for hook in getattr(hooks, name) if not isinstance(hook, TracingHook)]
        setattr(hooks, name, kept)


def tracing_hooks(client: Mistral) -> list[object]:
    """The SDK tracing hooks still registered on `client` (empty after `make_client`)."""
    hooks = client.sdk_configuration.__dict__["_hooks"]
    return [
        hook
        for name in _HOOK_LISTS
        for hook in getattr(hooks, name)
        if isinstance(hook, TracingHook)
    ]


def make_client(config: ProviderConfigSpec, api_key: str, http_client: Any = None) -> Mistral:
    """`http_client` is for tests only (a mock transport); production passes none."""
    client = Mistral(
        api_key=api_key,
        server_url=config.endpoint,
        client=http_client,
        retry_config=_NO_RETRY,
        timeout_ms=TIMEOUT_SECONDS * 1000,
        debug_logger=_silent_logger,
    )
    remove_tracing(client)
    return client


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            getattr(chunk, "text", "") or ""
            for chunk in content
            if getattr(chunk, "type", "") == "text"
        )
    return ""


def _usage(response: Any) -> CallUsage:
    """Conversations report connector (web search) tokens, billed as input, and calls per tool."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return NO_USAGE
    connectors = getattr(usage, "connectors", None) or {}
    return CallUsage(
        input_tokens=(usage.prompt_tokens or 0) + (getattr(usage, "connector_tokens", 0) or 0),
        output_tokens=usage.completion_tokens or 0,
        tool_calls=sum(connectors.values()),
    )


class MistralStructuring:
    def __init__(self, config: ProviderConfigSpec, client: Mistral) -> None:
        self._config = config
        self._client = client

    def generate_json(
        self, request: StructuringRequest, schema_name: str, json_schema: dict[str, object]
    ) -> StructuringOutput:
        messages: list[SystemMessage | UserMessage] = [
            SystemMessage(content=request.instructions),
            UserMessage(content=request.data),
        ]
        response = self._client.chat.complete(
            model=self._config.model_id,
            messages=messages,
            max_tokens=request.max_output_tokens,
            response_format=ResponseFormat(
                type="json_schema",
                json_schema=JSONSchema(
                    name=schema_name, schema_definition=json_schema, strict=False
                ),
            ),
        )
        choices = response.choices or []
        message = choices[0].message if choices else None
        text = _text(message.content) if message is not None else ""
        return StructuringOutput(text, _usage(response))


class MistralRetrieval:
    def __init__(self, config: ProviderConfigSpec, client: Mistral) -> None:
        self._config = config
        self._client = client

    def search(self, request: RetrievalRequest) -> RetrievalOutput:
        response = self._client.beta.conversations.start(
            model=self._config.model_id,
            instructions=request.instructions,
            inputs=request.query,
            tools=[WebSearchTool()],
            store=False,
        )
        urls: list[RetrievedUrl] = []
        for entry in response.outputs:
            content = getattr(entry, "content", None)
            if not isinstance(content, list):
                continue
            for chunk in content:
                url = getattr(chunk, "url", None)
                if getattr(chunk, "type", "") == "tool_reference" and isinstance(url, str) and url:
                    snippet = getattr(chunk, "description", None) or getattr(chunk, "title", "")
                    urls.append(
                        RetrievedUrl(url=url, snippet=snippet if isinstance(snippet, str) else "")
                    )
        return RetrievalOutput(urls, _usage(response))


def build_structuring(config: ProviderConfigSpec, api_key: str) -> MistralStructuring:
    return MistralStructuring(config, make_client(config, api_key))


def build_retrieval(config: ProviderConfigSpec, api_key: str) -> MistralRetrieval:
    return MistralRetrieval(config, make_client(config, api_key))

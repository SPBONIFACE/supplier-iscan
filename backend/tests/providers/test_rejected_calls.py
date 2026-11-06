"""A rejected provider call (#125): the log, and the Anthropic request in the documented shape.

The error bodies below are synthetic, in each vendor's documented error shape. The Anthropic
request follows https://platform.claude.com/docs/en/build-with-claude/structured-outputs (schema in
`output_config.format`, subset of JSON Schema) and the Messages API reference (top-level `system`,
`max_tokens`).
"""

import json
import logging
from typing import Any

import pytest
from pydantic import BaseModel

from app import llm_schemas
from app.providers.adapters import anthropic_adapter
from app.providers.errors import ProviderCallError
from app.providers.failures import provider_error_detail
from app.providers.interface import StructuringRequest
from tests.providers.support import CONTEXT, SENTINEL_KEY, Company, Recorder, fixture
from tests.providers.test_adapters import (
    ALL_CASES,
    STRUCTURING_CASES,
    Case,
    _id,
    call,
    structuring_client,
)
from tests.redacted import redacted

MESSAGE = "schema is not supported"
REJECTIONS: dict[str, tuple[Any, str]] = {
    "anthropic": (
        {"type": "error", "error": {"type": "invalid_request_error", "message": MESSAGE}},
        "invalid_request_error",
    ),
    "openai": (
        {"error": {"message": MESSAGE, "type": "invalid_request_error"}},
        "invalid_request_error",
    ),
    "perplexity": (
        {"error": {"message": MESSAGE, "type": "bad_request", "code": 400}},
        "bad_request",
    ),
    "google": (
        {"error": {"code": 400, "message": MESSAGE, "status": "INVALID_ARGUMENT"}},
        "INVALID_ARGUMENT",
    ),
    "mistral": (
        {"object": "error", "message": MESSAGE, "type": "invalid_request"},
        "invalid_request",
    ),
}


@pytest.mark.parametrize("case", ALL_CASES, ids=_id)
def test_a_rejected_call_logs_the_provider_error_type_and_message_only(
    case: Case, caplog: pytest.LogCaptureFixture
) -> None:
    body, error_type = REJECTIONS[case.provider]
    recorder = Recorder([(400, body)])

    with caplog.at_level(logging.WARNING), pytest.raises(ProviderCallError):
        if case in STRUCTURING_CASES:
            structuring_client(case, recorder).structure(
                StructuringRequest(
                    instructions="INSTRUCTION-SENTINEL", data=redacted("DATA-SENTINEL")
                ),
                Company,
                CONTEXT,
            )
        else:
            call(case, recorder)

    text = caplog.text
    assert f"provider_error_type={error_type}" in text
    assert f"provider_error_message={MESSAGE!r}" in text
    assert "status=400" in text
    for secret in (SENTINEL_KEY, "DATA-SENTINEL", "INSTRUCTION-SENTINEL", "Acme SA"):
        assert secret not in text


class Rejected(Exception):
    status_code = 400

    def __init__(self, message: str, kind: str = "invalid_request_error") -> None:
        super().__init__("not logged")
        self.body = {"type": "error", "error": {"type": kind, "message": message}}


PROMPT = "Confidential tender for Acme Holdings, budget 4.2M"
HOSTILE_MESSAGES = [
    f"messages.0.content: '{PROMPT}' is invalid",  # quoted
    f'messages.0.content: "{PROMPT}" is invalid',
    f"messages.0.content: `{PROMPT}` is invalid",
    f"messages.0.content: {PROMPT} is invalid",  # unquoted
    f"messages.0.content.{PROMPT.replace(' ', '_')}.text: invalid",  # in a parameter path
    f"system: {PROMPT[:30]}...",  # a fragment of 16 characters or more
    "contact bob.smith@example.com about this",  # email
    "see https://example.com/path?token=abc for details",  # URL
    "call +33 1 23 45 67 89 now",  # phone
    "invalid x-api-key sk-ant-api03-AbCdEf123456",  # key, prefixed
    "invalid key AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q",  # key, prefixed
    "invalid key 0123456789abcdef0123456789abcdef",  # hex
    "invalid key Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4",  # base64-like
    "unterminated quote 'secret text goes on",
]
SECRETS = [
    PROMPT,
    "Confidential tender",
    "bob.smith",
    "example.com",
    "sk-ant",
    "AIzaSy",
    "0123456789abcdef",
    "Zm9vYmFy",
    "secret text",
    "67 89",
]


@pytest.mark.parametrize("message", HOSTILE_MESSAGES)
def test_a_provider_message_that_may_echo_the_request_is_never_logged(message: str) -> None:
    logged = provider_error_detail(Rejected(message), (PROMPT, "Extract the supplier."))

    assert "provider_error_type=invalid_request_error" in logged
    for secret in SECRETS:
        assert secret.casefold() not in logged.casefold(), (secret, logged)


def test_a_message_sharing_a_long_run_with_the_request_is_withheld() -> None:
    logged = provider_error_detail(Rejected(f"bad value near {PROMPT[:20]} here"), (PROMPT,))

    assert logged == "provider_error_type=invalid_request_error provider_error_message=<withheld>"


@pytest.mark.parametrize(
    "message", ["max_tokens: field required", "output_config.format.schema: not supported"]
)
def test_a_harmless_message_is_still_logged(message: str) -> None:
    logged = provider_error_detail(Rejected(message), (PROMPT, "Extract the supplier."))

    assert f"provider_error_message={message!r}" in logged


def test_the_detail_is_empty_without_an_http_status_and_is_bounded() -> None:
    assert provider_error_detail(ValueError("anything")) == ""
    assert len(provider_error_detail(Rejected("word " * 500))) < 300
    assert provider_error_detail(Rejected("x", kind="has spaces and 'quotes'")) == (
        "provider_error_message='x'"
    )


def test_the_anthropic_request_is_in_the_documented_shape() -> None:
    case = STRUCTURING_CASES[0]
    recorder = Recorder([(200, fixture("anthropic.json")["structuring"])])

    call(case, recorder)

    body = json.loads(recorder.requests[0].content)
    assert set(body) == {"model", "max_tokens", "system", "messages", "output_config"}
    assert body["system"] == "Extract."
    assert body["messages"] == [{"role": "user", "content": "<data>Acme SA</data>"}]
    assert body["max_tokens"] == 8192
    assert body["output_config"]["format"]["type"] == "json_schema"


UNSUPPORTED = {
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "maxItems",
    "pattern",
    "default",
}


def _walk(node: Any, objects: list[dict[str, Any]], found: set[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            objects.append(node)
        found.update(key for key in node if key in UNSUPPORTED)
        for key, value in node.items():
            # A property named like a keyword is not a keyword: descend into its schema.
            children = value.values() if key == "properties" else [value]
            for child in children:
                _walk(child, objects, found)
    elif isinstance(node, list):
        for item in node:
            _walk(item, objects, found)


@pytest.mark.parametrize(
    "schema",
    [
        llm_schemas.FieldExtractionBatch,
        llm_schemas.FieldExtractionAnswer,
        llm_schemas.IdentityProposal,
        llm_schemas.AssessmentStatement,
        llm_schemas.AssessmentAnswer,
    ],
)
def test_the_anthropic_schema_keeps_only_what_the_api_accepts(schema: type[BaseModel]) -> None:
    raw = schema.model_json_schema()
    before = json.dumps(raw)

    sent = anthropic_adapter.api_schema(raw)

    objects: list[dict[str, Any]] = []
    found: set[str] = set()
    _walk(sent, objects, found)
    assert found == set()
    assert objects
    assert all(item["additionalProperties"] is False for item in objects)
    # The app's own schema, which validates the answer, is untouched.
    assert json.dumps(raw) == before
    assert "maxLength" in before or schema is llm_schemas.AssessmentAnswer or "default" in before

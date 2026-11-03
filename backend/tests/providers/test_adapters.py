"""Every adapter, on the real vendor SDK, against a mock transport (no network, no real key).

For each provider: the call goes to the configured endpoint with the key in the SDK's auth header
only; the structured output is validated against the schema; retrieval URLs come from the typed
citation fields; HTTP errors, timeouts and connection failures become typed provider errors; the
SDK does not retry on its own (#12 meters each attempt).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import httpx2
import pytest

from app.providers.adapters import (
    ADAPTERS,
    anthropic_adapter,
    google_adapter,
    mistral_adapter,
    openai_adapter,
    perplexity_adapter,
)
from app.providers.catalogue import PROVIDER_APIS, ProviderConfigSpec
from app.providers.errors import ProviderCallError, StructuredOutputInvalid
from app.providers.interface import (
    RetrievalClient,
    RetrievalRequest,
    StructuringClient,
    StructuringRequest,
)
from tests.providers.support import (
    CONTEXT,
    SENTINEL_KEY,
    Company,
    Recorder,
    config,
    fixture,
    httpx2_client,
    httpx_client,
    make_meter,
)
from tests.redacted import redacted

ENDPOINT = "https://provider.example.test"
EXPECTED_URLS = ["https://acme.example/report", "https://acme.example/about"]


@dataclass(frozen=True)
class Case:
    provider: str
    api: str
    make_client: Callable[..., Any]
    adapter: type
    transport: str  # "httpx" or "httpx2": the HTTP library the SDK is built on
    path: str  # path of the call, after the endpoint
    auth_header: str
    auth_value: str
    retrieval_api: str | None = None

    @property
    def library(self) -> Any:
        return httpx if self.transport == "httpx" else httpx2

    def client_factory(self, recorder: Recorder) -> Any:
        return httpx_client(recorder) if self.transport == "httpx" else httpx2_client(recorder)

    def build(self, recorder: Recorder, api: str | None = None, endpoint: str = ENDPOINT) -> Any:
        cfg = self.config(api, endpoint)
        return cfg, self.make_client(cfg, SENTINEL_KEY, self.client_factory(recorder))

    def config(self, api: str | None = None, endpoint: str = ENDPOINT) -> ProviderConfigSpec:
        return config(f"{self.provider}-test", self.provider, api or self.api, endpoint)


BEARER = f"Bearer {SENTINEL_KEY}"
STRUCTURING_CASES = [
    Case(
        "anthropic",
        "messages",
        anthropic_adapter.make_client,
        anthropic_adapter.ClaudeStructuring,
        "httpx2",
        "/v1/messages",
        "x-api-key",
        SENTINEL_KEY,
    ),
    Case(
        "google",
        "generate_content",
        google_adapter.make_client,
        google_adapter.GeminiStructuring,
        "httpx",
        "/v1beta/models/model-1:generateContent",
        "x-goog-api-key",
        SENTINEL_KEY,
    ),
    Case(
        "openai",
        "responses",
        openai_adapter.make_client,
        openai_adapter.OpenAIStructuring,
        "httpx2",
        "/responses",
        "authorization",
        BEARER,
    ),
    Case(
        "mistral",
        "chat_completions",
        mistral_adapter.make_client,
        mistral_adapter.MistralStructuring,
        "httpx2",
        "/v1/chat/completions",
        "authorization",
        BEARER,
    ),
    Case(
        "perplexity",
        "chat_completions",
        perplexity_adapter.make_client,
        perplexity_adapter.PerplexityStructuring,
        "httpx",
        "/chat/completions",
        "authorization",
        BEARER,
    ),
]
RETRIEVAL_CASES = [
    Case(
        "anthropic",
        "messages",
        anthropic_adapter.make_client,
        anthropic_adapter.ClaudeRetrieval,
        "httpx2",
        "/v1/messages",
        "x-api-key",
        SENTINEL_KEY,
    ),
    Case(
        "google",
        "generate_content",
        google_adapter.make_client,
        google_adapter.GeminiRetrieval,
        "httpx",
        "/v1beta/models/model-1:generateContent",
        "x-goog-api-key",
        SENTINEL_KEY,
    ),
    Case(
        "openai",
        "responses",
        openai_adapter.make_client,
        openai_adapter.OpenAIRetrieval,
        "httpx2",
        "/responses",
        "authorization",
        BEARER,
    ),
    Case(
        "mistral",
        "conversations",
        mistral_adapter.make_client,
        mistral_adapter.MistralRetrieval,
        "httpx2",
        "/v1/conversations",
        "authorization",
        BEARER,
    ),
    Case(
        "perplexity",
        "chat_completions",
        perplexity_adapter.make_client,
        perplexity_adapter.PerplexityRetrieval,
        "httpx",
        "/chat/completions",
        "authorization",
        BEARER,
    ),
]
ALL_CASES = [*STRUCTURING_CASES, *RETRIEVAL_CASES]


def _id(case: Case) -> str:
    return f"{case.provider}-{case.adapter.__name__}"


def structuring_client(case: Case, recorder: Recorder) -> StructuringClient:
    cfg, client = case.build(recorder)
    return StructuringClient(cfg, case.adapter(cfg, client), make_meter())


def retrieval_client(case: Case, recorder: Recorder) -> RetrievalClient:
    cfg, client = case.build(recorder)
    return RetrievalClient(cfg, case.adapter(cfg, client), make_meter())


def call(case: Case, recorder: Recorder) -> Any:
    if case in STRUCTURING_CASES:
        return structuring_client(case, recorder).structure(
            StructuringRequest(instructions="Extract.", data=redacted("<data>Acme SA</data>")),
            Company,
            CONTEXT,
        )
    return retrieval_client(case, recorder).retrieve(
        RetrievalRequest(instructions="Find sources.", query=redacted("Acme SA annual report")),
        CONTEXT,
    )


def test_every_listed_api_has_an_adapter_for_each_of_its_roles() -> None:
    assert set(ADAPTERS) == set(PROVIDER_APIS)
    for pair, roles in PROVIDER_APIS.items():
        factories = ADAPTERS[pair]
        assert (factories.structuring is not None) == ("structuring" in roles), pair
        assert (factories.retrieval is not None) == ("retrieval" in roles), pair
    providers = {provider for provider, _api in PROVIDER_APIS}
    assert providers == {"anthropic", "google", "openai", "mistral", "perplexity"}
    for role in ("structuring", "retrieval"):
        assert {p for (p, _a), roles in PROVIDER_APIS.items() if role in roles} == providers


@pytest.mark.parametrize("case", STRUCTURING_CASES, ids=_id)
def test_structuring_returns_the_validated_schema(case: Case) -> None:
    recorder = Recorder([(200, fixture(f"{case.provider}.json")["structuring"])])

    result = call(case, recorder)

    assert result == Company(legal_name="Acme SA", country="FR")
    (request,) = recorder.requests
    assert str(request.url).startswith(ENDPOINT + case.path)
    assert request.headers[case.auth_header] == case.auth_value
    body = json.loads(request.content)
    # The schema, the model, the instructions and the data are all in the request.
    text = json.dumps(body) + str(request.url)
    assert "model-1" in text and "Extract." in text and "<data>Acme SA</data>" in text
    assert "legal_name" in text
    assert SENTINEL_KEY not in text


@pytest.mark.parametrize("case", RETRIEVAL_CASES, ids=_id)
def test_retrieval_returns_the_cited_urls(case: Case) -> None:
    recorder = Recorder([(200, fixture(f"{case.provider}.json")["retrieval"])])

    result = call(case, recorder)

    assert sorted(item.url for item in result.urls) == sorted(EXPECTED_URLS)
    assert len(result.urls) == len(EXPECTED_URLS)  # duplicates removed
    # The answer text is never used as a snippet.
    assert all("publishes an annual report" not in item.snippet for item in result.urls)
    (request,) = recorder.requests
    assert str(request.url).startswith(ENDPOINT + case.path)
    assert request.headers[case.auth_header] == case.auth_value
    assert "Acme SA annual report" in request.content.decode()


@pytest.mark.parametrize("case", STRUCTURING_CASES, ids=_id)
def test_a_schema_failure_is_retried_once_then_raised(case: Case) -> None:
    answer = json.loads(json.dumps(fixture(f"{case.provider}.json")["structuring"]))
    invalid = json.dumps(answer).replace('\\"country\\": \\"FR\\"', '\\"country\\": 33')
    assert invalid != json.dumps(answer)
    recorder = Recorder([(200, json.loads(invalid)), (200, json.loads(invalid))])

    with pytest.raises(StructuredOutputInvalid) as raised:
        call(case, recorder)

    assert len(recorder.requests) == 2
    assert raised.value.schema_name == "Company"
    assert raised.value.config_id == f"{case.provider}-test"


@pytest.mark.parametrize("case", STRUCTURING_CASES, ids=_id)
def test_a_schema_failure_then_a_valid_output_succeeds(case: Case) -> None:
    good = fixture(f"{case.provider}.json")["structuring"]
    bad = json.loads(json.dumps(good).replace("Acme SA", "").replace('\\"country\\": \\"FR\\"', ""))
    recorder = Recorder([(200, bad), (200, good)])

    assert call(case, recorder) == Company(legal_name="Acme SA", country="FR")
    assert len(recorder.requests) == 2


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, "authentication"),
        (403, "authentication"),
        (400, "rejected"),
        (404, "rejected"),
        (429, "rate_limited"),
        (500, "unavailable"),
        (503, "unavailable"),
    ],
)
@pytest.mark.parametrize("case", ALL_CASES, ids=_id)
def test_http_errors_become_typed_provider_errors(case: Case, status: int, kind: str) -> None:
    recorder = Recorder([(status, fixture(f"{case.provider}.json")["error"])] * 3)

    with pytest.raises(ProviderCallError) as raised:
        call(case, recorder)

    error = raised.value
    assert (error.kind, error.status_code) == (kind, status)
    assert error.provider == case.provider
    assert error.config_id == f"{case.provider}-test"
    assert error.retryable is True
    assert f"HTTP {status}" in str(error)
    assert SENTINEL_KEY not in str(error) and SENTINEL_KEY not in repr(error)
    # The vendor's error text (which can quote the request) is not carried over.
    assert "key provided" not in str(error) and "not valid" not in str(error)
    assert error.__cause__ is None and error.__context__ is None
    # No SDK retry: one request per call (#12 meters each attempt).
    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    ("error_name", "kind"), [("ReadTimeout", "timeout"), ("ConnectError", "connection")]
)
@pytest.mark.parametrize("case", ALL_CASES, ids=_id)
def test_transport_failures_become_typed_provider_errors(
    case: Case, error_name: str, kind: str
) -> None:
    failure = getattr(case.library, error_name)("failed for " + SENTINEL_KEY)
    recorder = Recorder([failure] * 3)

    with pytest.raises(ProviderCallError) as raised:
        call(case, recorder)

    assert raised.value.kind == kind
    assert raised.value.status_code is None
    assert SENTINEL_KEY not in str(raised.value)
    assert raised.value.__context__ is None
    assert len(recorder.requests) == 1


def test_the_mistral_client_has_no_sdk_tracing_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    # With MISTRAL_SDK_TELEMETRY set, the SDK would export spans (with prompt and response
    # content) to Mistral; with its hook removed it creates no span and sends nothing else.
    monkeypatch.setenv("MISTRAL_SDK_TELEMETRY", "dedicated")
    monkeypatch.setenv("MISTRAL_DEBUG", "1")
    recorder = Recorder([(200, fixture("mistral.json")["structuring"])])
    case = STRUCTURING_CASES[3]
    cfg, client = case.build(recorder)

    assert mistral_adapter.tracing_hooks(client) == []
    StructuringClient(cfg, case.adapter(cfg, client), make_meter()).structure(
        StructuringRequest(instructions="Extract.", data=redacted("Acme SA")), Company, CONTEXT
    )
    assert [request.url.path for request in recorder.requests] == ["/v1/chat/completions"]


def test_a_new_mistral_sdk_client_does_register_the_tracing_hook() -> None:
    # Guards the test above: the hook exists in the SDK, so removing it is what disables it.
    from mistralai.client import Mistral

    assert mistral_adapter.tracing_hooks(Mistral(api_key=SENTINEL_KEY)) != []


@pytest.mark.parametrize("case", ALL_CASES, ids=_id)
def test_the_production_factory_builds_a_client_without_retries(case: Case) -> None:
    factories = ADAPTERS[(case.config().provider, case.api)]
    factory = factories.structuring if case in STRUCTURING_CASES else factories.retrieval
    assert factory is not None

    adapter: Any = factory(case.config(), SENTINEL_KEY)

    client = adapter._client  # noqa: SLF001 - inspecting the SDK client the factory built
    if hasattr(client, "max_retries"):
        assert client.max_retries == 0
    assert SENTINEL_KEY not in repr(adapter)

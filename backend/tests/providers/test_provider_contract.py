"""One contract suite for every approved provider configuration and output mode (#12).

For each configuration of the shipped list and each role it serves (structured extraction, URL
retrieval), the real vendor SDK runs against a recorded exchange replayed by a mock transport: no
network, no key. The suite checks that the structured output validates against the
`FieldExtraction` schema, that every cited `source_id` is in the input, and that every quote is in
that source's text verbatim (exact matching; normalisation is #23). A configuration or mode
without a recording fails the suite. Recordings: tests/providers/README.md.
"""

import json
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import pytest

from app.llm_schemas import FieldExtractionBatch
from app.providers.catalogue import (
    ROLES,
    ProviderCatalogue,
    ProviderConfigSpec,
    Role,
    load_catalogue,
)
from app.providers.interface import (
    RetrievalClient,
    RetrievalRequest,
    StructuringClient,
    StructuringRequest,
)
from app.providers.metering import ListSink, UsageEntry, UsageMeter
from app.providers.pricing import PriceTable, load_price_table
from tests.providers.replay import (
    HTTP_LIBRARY,
    RECORDINGS,
    adapter_for,
    load_input,
    recording_path,
    render_sources,
)
from tests.providers.support import (
    CONTEXT,
    SENTINEL_KEY,
    Recorder,
    config,
    httpx2_client,
    httpx_client,
)
from tests.redacted import redacted

CATALOGUE = load_catalogue()  # the shipped list of approved configurations
PRICES = load_price_table()
MODES = [
    (item.id, role) for item in CATALOGUE.provider_configs for role in ROLES if role in item.roles
]


def missing_recordings(catalogue: ProviderCatalogue) -> list[str]:
    return [
        recording_path(item.id, role).name
        for item in catalogue.provider_configs
        for role in ROLES
        if role in item.roles and not recording_path(item.id, role).exists()
    ]


def load_recording(config_id: str, role: str) -> dict[str, Any]:
    path = recording_path(config_id, role)
    assert path.exists(), (
        f"No recording for configuration {config_id!r}, role {role}: add {path.name} "
        "(tests/providers/README.md)"
    )
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def _meter(prices: PriceTable = PRICES) -> tuple[UsageMeter, ListSink]:
    sink = ListSink()
    return UsageMeter(prices, Decimal("0.92"), sink), sink


def _run(spec: ProviderConfigSpec, role: Role, recording: dict[str, Any]) -> Any:
    recorder = Recorder([(recording["status"], recording["body"])])
    library = HTTP_LIBRARY[spec.provider]
    http = httpx_client(recorder) if library.__name__ == "httpx" else httpx2_client(recorder)
    adapter = adapter_for(spec, role, http, SENTINEL_KEY)
    meter, sink = _meter()
    material = load_input()
    result: Any
    if role == "structuring":
        request = StructuringRequest(
            instructions=material["instructions"],
            data=redacted(render_sources(material["sources"])),
        )
        result = StructuringClient(spec, adapter, meter).structure(
            request, FieldExtractionBatch, CONTEXT
        )
    else:
        result = RetrievalClient(spec, adapter, meter).retrieve(
            RetrievalRequest(
                instructions=material["retrieval_instructions"], query=redacted(material["query"])
            ),
            CONTEXT,
        )
    assert len(recorder.requests) == 1 and len(sink.entries) == 1
    return result, sink.entries[0], recorder


def _check_usage(entry: UsageEntry, recording: dict[str, Any]) -> None:
    expected = recording["expected_usage"]
    assert entry.outcome == "success"
    for name in ("input_tokens", "output_tokens", "reasoning_tokens", "tool_calls"):
        assert getattr(entry, name) == expected[name], name
    assert entry.cost > 0
    if "billed_amount" in expected:
        assert (entry.cost_basis, entry.billed_currency) == (
            "provider",
            expected["billed_currency"],
        )
        assert entry.billed_amount == Decimal(expected["billed_amount"])
    else:
        assert entry.cost_basis == "price_table"
    assert entry.cost == (entry.billed_amount * entry.exchange_rate).quantize(Decimal("1e-8"))


@pytest.mark.parametrize(("config_id", "role"), MODES, ids=[f"{c}-{r}" for c, r in MODES])
def test_the_recording_satisfies_the_contract(config_id: str, role: Role) -> None:
    recording = load_recording(config_id, role)
    spec = CATALOGUE.by_id[config_id]
    result, entry, recorder = _run(spec, role, recording)
    material = load_input()

    if role == "structuring":
        sources = {item["source_id"]: item["text"] for item in material["sources"]}
        extractions = result.extractions
        assert {item.field for item in extractions} == set(material["fields"])
        assert any(item.status == "found" for item in extractions)
        assert any(item.status == "not_found" for item in extractions)
        for item in extractions:
            if item.status == "found":
                assert item.source_id in sources, f"{item.field}: unknown source_id"
                quote_found = item.quote in sources[item.source_id]
                assert quote_found, f"{item.field}: quote not verbatim"
        # The request carried the instructions, the sources and the schema.
        sent = recorder.requests[0].content.decode()
        assert "S2" in sent and "extractions" in sent
    else:
        urls = [item.url for item in result.urls]
        assert urls and len(urls) == len(set(urls))
        assert urls == recording["expected_urls"]
        assert all(urlsplit(url).scheme in ("http", "https") for url in urls)

    _check_usage(entry, recording)
    # The record holds counts and identifiers, never the prompt, the quotes or the answer.
    text = repr(entry)
    assert not any(item["text"][:30] in text for item in material["sources"])
    assert SENTINEL_KEY not in text


@pytest.mark.parametrize(("config_id", "role"), MODES, ids=[f"{c}-{r}" for c, r in MODES])
def test_every_approved_configuration_and_mode_has_a_recording(config_id: str, role: str) -> None:
    load_recording(config_id, role)


def test_a_configuration_added_without_recordings_fails_the_suite() -> None:
    extra = config("brand-new", "mistral", "chat_completions")
    catalogue = CATALOGUE.model_copy(
        update={"provider_configs": [*CATALOGUE.provider_configs, extra]}
    )
    assert missing_recordings(catalogue) == ["brand-new.structuring.json"]
    assert missing_recordings(CATALOGUE) == []


def test_no_recording_is_left_without_a_configuration() -> None:
    expected = {recording_path(config_id, role).name for config_id, role in MODES}
    found = {path.name for path in RECORDINGS.glob("*.*.json")}
    assert found == expected


def test_every_approved_model_has_a_price() -> None:
    for item in CATALOGUE.provider_configs:
        assert PRICES.find(item.provider, item.model_id) is not None, item.model_id


def test_recordings_hold_no_key_and_no_email_address() -> None:
    for path in RECORDINGS.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "@" not in text, path.name
        assert "api_key" not in text.lower() and "sk-" not in text, path.name

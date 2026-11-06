"""Perplexity Agent API: the documented response shape, optional fields, the validation log and the
shape diagnostic (#122). Fixtures: `fixtures/perplexity.json` (origin in each `$comment`: the
documented examples, not live recordings). No key, no network.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from app.providers.errors import ProviderCallError, StructuredOutputInvalid
from app.providers.interface import (
    RetrievalClient,
    RetrievalRequest,
    RetrievedUrl,
    StructuringClient,
    StructuringRequest,
)
from app.providers.shape import write_shape
from tests.providers.support import CONTEXT, Recorder, fixture, make_meter
from tests.providers.test_adapters import RETRIEVAL_CASES, STRUCTURING_CASES, Case
from tests.redacted import redacted


def _case(cases: list[Case]) -> Case:
    return next(case for case in cases if case.provider == "perplexity")


def _documented() -> Any:
    return json.loads(json.dumps(fixture("perplexity.json")["retrieval_documented"]))


def _search(body: Any) -> Any:
    case = _case(RETRIEVAL_CASES)
    cfg, client = case.build(Recorder([(200, body)]))
    adapter = case.adapter(cfg, client)
    return adapter.search(RetrievalRequest(instructions="Find.", query=redacted("Acme SA")))


def test_retrieval_reads_the_documented_response_shape() -> None:
    output = _search(_documented())

    assert [item.url for item in output.urls] == [
        "https://acme.example/about",
        "https://acme.example/report",
        "https://register.example/acme-sa",
    ]
    # A null snippet falls back to the title; null dates are accepted.
    assert output.urls[2].snippet == "Acme SA on a register"
    assert output.usage.billed_amount == Decimal("0.0053")
    assert output.usage.tool_calls == 1


def test_retrieval_cuts_a_long_snippet_and_skips_an_unusable_entry() -> None:
    # One odd entry never fails the response: the snippet only ranks, so it is cut; an entry
    # without a text URL, or with an over-long one, is skipped.
    body = _documented()
    results = body["output"][0]["results"]
    results[0]["snippet"] = "x" * 9000
    results[1]["url"] = None
    results[2]["url"] = "https://register.example/" + "a" * 5000
    results.append({"id": 4, "snippet": "s", "title": "t", "url": 12})
    results.append({"id": 5})

    output = _search(body)

    assert [item.url for item in output.urls] == ["https://acme.example/about"]
    assert len(output.urls[0].snippet) == 4000


def test_usage_tolerates_null_counts() -> None:
    body = _documented()
    body["usage"] = {"input_tokens": None, "output_tokens": None, "cost": None}

    usage = _search(body).usage

    assert (usage.input_tokens, usage.output_tokens, usage.tool_calls) == (0, 0, 0)
    assert usage.billed_amount is None


class Branch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str
    phone: str = ""


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: str
    country: str
    website: str = ""
    branches: list[Branch] = []


def _structuring(body: Any, responses: int = 1) -> StructuringClient:
    case = _case(STRUCTURING_CASES)
    cfg, client = case.build(Recorder([(200, body)] * responses))
    return StructuringClient(cfg, case.adapter(cfg, client), make_meter())


def _structure(client: StructuringClient) -> Profile:
    request = StructuringRequest(instructions="Extract.", data=redacted("<data>Acme SA</data>"))
    return client.structure(request, Profile, CONTEXT)


def test_structuring_drops_nulls_of_properties_that_are_not_required() -> None:
    # Docs, Structured Outputs: a declared property outside `required` may come back as null.
    profile = _structure(_structuring(fixture("perplexity.json")["structuring_with_nulls"]))

    assert profile.website == "" and profile.branches[0].phone == ""
    assert profile.legal_name == "Acme SA" and profile.branches[0].city == "Lyon"


def test_structuring_keeps_a_null_in_a_required_property_for_the_schema_to_reject() -> None:
    body = json.loads(json.dumps(fixture("perplexity.json")["structuring_with_nulls"]))
    body["output"][0]["content"][0]["text"] = '{"legal_name": null, "country": "FR"}'

    with pytest.raises(StructuredOutputInvalid):
        _structure(_structuring(body, responses=2))


def test_validation_failure_log_names_the_field_and_the_types_but_no_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "SECRET-SNIPPET-" + "z" * 4100

    class Failing:
        def search(self, request: RetrievalRequest) -> Any:
            return RetrievedUrl(url="https://acme.example", snippet=secret)

    cfg, _client = _case(RETRIEVAL_CASES).build(Recorder([]))
    client = RetrievalClient(cfg, Failing(), make_meter())

    with caplog.at_level("WARNING"), pytest.raises(ProviderCallError):
        client.retrieve(RetrievalRequest(instructions="Find.", query=redacted("Acme")), CONTEXT)

    text = caplog.text
    assert "kind=invalid_response" in text and "error=ValidationError" in text
    assert "snippet rule=string_too_long received=str" in text
    assert "SECRET-SNIPPET" not in text and "https://acme.example" not in text


def test_the_adapter_writes_nothing_whatever_the_environment_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only `make provider-shape` writes a shape; no setting makes the application do it.
    monkeypatch.setenv("PROVIDER_SHAPE_DIAGNOSTIC", "1")
    monkeypatch.setenv("PROVIDER_SHAPE_DIR", str(tmp_path / "out"))
    monkeypatch.chdir(tmp_path)

    _search(_documented())

    assert list(tmp_path.iterdir()) == []


def test_the_retrieval_output_carries_the_response_for_the_shape_command() -> None:
    assert _search(_documented()).raw is not None


def test_write_shape_writes_names_and_types_only(tmp_path: Path) -> None:
    output = _search(_documented())

    written = write_shape("perplexity", "retrieval", output.raw, tmp_path / "out")

    assert written is not None
    text = written.read_text(encoding="utf-8")
    shape = json.loads(text)["shape"]
    result = shape["output"]["items"][0]["results"]["items"][0]
    assert result["url"].startswith("str(") and result["date"] == "null"
    assert shape["usage"]["cost"]["total_cost"] == "float"
    # No text, no URL, no title from the response.
    for content in ("acme.example", "Acme SA", "annual report", "register"):
        assert content not in text

"""Shared helpers for the provider tests: configurations, catalogues, recorded HTTP exchanges.

Adapter tests run the real vendor SDK against a mock transport: no network, no real key. Each
recorded exchange is a request check and a fixed JSON answer.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import httpx2
from pydantic import BaseModel, ConfigDict

from app.providers.catalogue import PROVIDER_NAMES, ProviderCatalogue, ProviderConfigSpec
from app.providers.metering import CallContext, ListSink, UsageMeter
from app.providers.pricing import PriceTable

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# A recognisable value that must never appear anywhere outside the SDK's own request header.
SENTINEL_KEY = "sk-SENTINEL-4f9c2a7e1b3d-never-leak"

VERIFIED_AT = datetime(2026, 10, 20, tzinfo=UTC)


def config(
    config_id: str,
    provider: str = "google",
    api: str = "generate_content",
    endpoint: str = "https://provider.example.test",
    *,
    enabled: bool = True,
    verified: bool = True,
    model_id: str = "model-1",
) -> ProviderConfigSpec:
    return ProviderConfigSpec.model_validate(
        {
            "id": config_id,
            "provider": provider,
            "api": api,
            "model_id": model_id,
            "endpoint": endpoint,
            "training_setting": "no training on API data (test)",
            "retention": "30 days (test)",
            "region": "EU (test)",
            "transfer_mechanism": "none (test)",
            "verified_at": VERIFIED_AT if verified else None,
            "enabled": enabled,
        }
    )


def catalogue(
    *configs: ProviderConfigSpec, retrieval: str | None = None, structuring: str | None = None
) -> ProviderCatalogue:
    first = configs[0].id
    return ProviderCatalogue.model_validate(
        {
            "provider_configs": [item.model_dump() for item in configs],
            "roles": {"retrieval": retrieval or first, "structuring": structuring or first},
        }
    )


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Company(BaseModel):
    """A small output schema for the tests (feature schemas belong to #16, #20, #23, #25)."""

    model_config = ConfigDict(extra="forbid")

    legal_name: str
    country: str


@dataclass
class Recorder:
    """Answers every request with the next scripted (status, JSON body) and keeps the requests."""

    answers: list[tuple[int, Any] | Exception]
    requests: list[Any] = field(default_factory=list)

    def answer(self, request: Any) -> tuple[int, Any]:
        self.requests.append(request)
        if not self.answers:
            raise AssertionError("unexpected extra request")
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def body(self, index: int = -1) -> Any:
        return json.loads(self.requests[index].content)


def httpx_client(recorder: Recorder) -> httpx.Client:
    """For the SDKs built on `httpx` (google-genai, perplexityai)."""

    def handler(request: httpx.Request) -> httpx.Response:
        status, body = recorder.answer(request)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def httpx2_client(recorder: Recorder) -> httpx2.Client:
    """For the SDKs built on `httpx2` (anthropic, openai, mistralai)."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        status, body = recorder.answer(request)
        return httpx2.Response(status, json=body)

    return httpx2.Client(transport=httpx2.MockTransport(handler))


ClientFactory = Callable[[Recorder], Any]


# Test prices: every provider has "model-1" and "model-2" (USD, 1 USD = 0.9 EUR).
EUR_PER_USD = Decimal("0.9")
PRICES = PriceTable.model_validate(
    {
        "prices": [
            {
                "provider": provider,
                "model_id": model,
                "currency": "USD",
                "as_of": "2026-10-27",
                "input_per_million": "1.00",
                "output_per_million": "4.00",
                "tool_call": "0.01",
            }
            for provider in PROVIDER_NAMES
            for model in ("model-1", "model-2")
        ]
    }
)
CONTEXT = CallContext(organisation_id=uuid.UUID(int=1))


def make_meter(sink: ListSink | None = None) -> UsageMeter:
    return UsageMeter(PRICES, EUR_PER_USD, sink if sink is not None else ListSink())

"""A fake provider for tests: scripted outputs, recorded calls, no network.

    fake = FakeStructuringAdapter(['{"name": "Acme"}'])
    providers = Providers(catalogue, environ, adapters=fake_adapters(catalogue, structuring=fake))

Each scripted item is the JSON text the provider returns (or a full output with its usage), or an
exception it raises.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.providers.catalogue import ProviderCatalogue, ProviderConfigSpec, ProviderName
from app.providers.interface import (
    RetrievalOutput,
    RetrievalRequest,
    RetrievedUrl,
    StructuringOutput,
    StructuringRequest,
)
from app.providers.registry import AdapterFactories, AdapterTable


@dataclass
class FakeStructuringAdapter:
    outputs: list[str | StructuringOutput | Exception]
    calls: list[StructuringRequest] = field(default_factory=list)
    schemas: list[str] = field(default_factory=list)

    def generate_json(
        self, request: StructuringRequest, schema_name: str, json_schema: dict[str, object]
    ) -> StructuringOutput:
        self.calls.append(request)
        self.schemas.append(schema_name)
        if not self.outputs:
            raise AssertionError("FakeStructuringAdapter: no scripted output left")
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output if isinstance(output, StructuringOutput) else StructuringOutput(output)


@dataclass
class FakeRetrievalAdapter:
    results: list[list[RetrievedUrl] | RetrievalOutput | Exception]
    calls: list[RetrievalRequest] = field(default_factory=list)

    def search(self, request: RetrievalRequest) -> RetrievalOutput:
        self.calls.append(request)
        if not self.results:
            raise AssertionError("FakeRetrievalAdapter: no scripted result left")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result if isinstance(result, RetrievalOutput) else RetrievalOutput(result)


@dataclass
class FactoryLog:
    """The configurations an adapter was built for, in order."""

    built: list[str] = field(default_factory=list)


def fake_adapters(
    catalogue: ProviderCatalogue,
    structuring: dict[str, FakeStructuringAdapter] | FakeStructuringAdapter | None = None,
    retrieval: dict[str, FakeRetrievalAdapter] | FakeRetrievalAdapter | None = None,
    log: FactoryLog | None = None,
) -> AdapterTable:
    """An adapter table in which every (provider, api) pair of `catalogue` builds a fake.

    Pass one fake for every configuration, or a dict keyed by configuration id.
    """

    def pick[A](fakes: dict[str, A] | A | None, config: ProviderConfigSpec) -> A:
        if isinstance(fakes, dict):
            return fakes[config.id]
        if fakes is None:
            raise AssertionError(f"no fake adapter for configuration {config.id}")
        return fakes

    def structuring_factory(config: ProviderConfigSpec, _key: str) -> FakeStructuringAdapter:
        if log is not None:
            log.built.append(config.id)
        return pick(structuring, config)

    def retrieval_factory(config: ProviderConfigSpec, _key: str) -> FakeRetrievalAdapter:
        if log is not None:
            log.built.append(config.id)
        return pick(retrieval, config)

    pairs: Iterable[tuple[ProviderName, str]] = {
        (config.provider, config.api) for config in catalogue.provider_configs
    }
    return {
        pair: AdapterFactories(structuring=structuring_factory, retrieval=retrieval_factory)
        for pair in pairs
    }

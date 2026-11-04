"""Where the models come from: the fake provider (recorded answers) or an approved configuration.

Live: the configuration (`CONFIG`) is looked up in the approved list (`PROVIDER_CONFIG_FILE`), its
price in the price table (`PRICE_TABLE_FILE`), its key in the environment by name. Nothing here
reads a key value except the provider registry, which hands it to the vendor SDK. Fake: no key, no
network; the answers recorded in the cases are replayed, so the run proves the plumbing only.
"""

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.config import ConfigurationError, load_settings
from app.http_client import FetchError, GuardedClient
from app.providers import ProviderCatalogue, ProviderConfigSpec, Providers, load_catalogue
from app.providers.catalogue import RoleDefaults
from app.providers.fake import FakeRetrievalAdapter, FakeStructuringAdapter, fake_adapters
from app.providers.interface import RetrievedUrl
from app.providers.metering import ListSink, UsageMeter
from app.providers.pricing import PriceTable, check_prices, load_price_table

FAKE_CONFIG_ID = "fake"
FAKE_MODEL_ID = "fake-recorded"
FAKE_KEY_SETTING = "GEMINI_API_KEY"
FAKE_NOTE = "fake provider: plumbing only"
RETRIEVAL_CONFIG_ENV = "RETRIEVAL_CONFIG"


def _fake_catalogue() -> ProviderCatalogue:
    spec = ProviderConfigSpec.model_validate(
        {
            "id": FAKE_CONFIG_ID,
            "provider": "google",
            "api": "generate_content",
            "model_id": FAKE_MODEL_ID,
            "endpoint": "https://fake.invalid",
            "training_setting": "none (fake)",
            "retention": "none (fake)",
            "region": "none (fake)",
            "transfer_mechanism": "none (fake)",
            "verified_at": datetime(2026, 11, 5, tzinfo=UTC),
            "enabled": True,
        }
    )
    return ProviderCatalogue(
        provider_configs=[spec],
        roles=RoleDefaults(retrieval=FAKE_CONFIG_ID, structuring=FAKE_CONFIG_ID),
    )


def _fake_prices() -> PriceTable:
    return PriceTable.model_validate(
        {
            "prices": [
                {
                    "provider": "google",
                    "model_id": FAKE_MODEL_ID,
                    "currency": "EUR",
                    "as_of": "2026-11-05",
                    "input_per_million": "0",
                    "output_per_million": "0",
                    "tool_call": "0",
                }
            ]
        }
    )


@dataclass
class Backend:
    """What a run needs from the providers side."""

    fake: bool
    catalogue: ProviderCatalogue
    structuring_config: ProviderConfigSpec
    retrieval_config: ProviderConfigSpec
    meter: UsageMeter
    sink: ListSink
    environ: dict[str, str] = field(repr=False)
    _live: Providers | None = field(default=None, repr=False)

    def providers(
        self,
        structuring: list[Any] | None = None,
        retrieval: list[list[RetrievedUrl]] | None = None,
    ) -> Providers:
        """Fake: a fresh provider set replaying this case's recorded answers. Live: one set."""
        if not self.fake:
            if self._live is None:
                self._live = Providers(self.catalogue, self.environ, meter=self.meter)
            return self._live
        adapters = fake_adapters(
            self.catalogue,
            structuring=FakeStructuringAdapter(list(structuring or [])),
            retrieval=FakeRetrievalAdapter(list(retrieval or [])),
        )
        return Providers(self.catalogue, self.environ, adapters, meter=self.meter)

    def verifier(self) -> "UrlVerifier":
        return UrlVerifier(live=not self.fake)


class UrlVerifier:
    """Can a returned address be verified? Recorded: it is on the case's list of reachable pages.
    Live: the guarded client (#15) fetches it and it answers below 400."""

    def __init__(self, live: bool) -> None:
        self._live = live
        self._client: GuardedClient | None = None

    def verified(self, url: str, reachable: set[str]) -> bool:
        if not self._live:
            return url in reachable
        if self._client is None:
            self._client = GuardedClient()
        try:
            return self._client.get(url).status_code < 400
        except FetchError:
            return False

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


def fake_backend() -> Backend:
    catalogue = _fake_catalogue()
    sink = ListSink()
    meter = UsageMeter(_fake_prices(), None, sink)
    config = catalogue.by_id[FAKE_CONFIG_ID]
    return Backend(
        True, catalogue, config, config, meter, sink, {FAKE_KEY_SETTING: "fake-not-a-key"}
    )


def live_backend(config_id: str, environ: dict[str, str] | None = None) -> Backend:
    """An approved configuration for the structuring role. Raises `ConfigurationError`."""
    env = dict(os.environ if environ is None else environ)
    settings = load_settings(env)
    catalogue = load_catalogue(
        Path(settings.provider_config_file) if settings.provider_config_file else None
    )
    prices = load_price_table(
        Path(settings.price_table_file) if settings.price_table_file else None
    )
    check_prices(catalogue, prices, settings.eur_per_usd)
    structuring_id = config_id or catalogue.default_for("structuring")
    retrieval_id = env.get(RETRIEVAL_CONFIG_ENV, "").strip() or catalogue.default_for("retrieval")
    for role_id in (structuring_id, retrieval_id):
        if role_id not in catalogue.by_id:
            raise ConfigurationError(
                f"Configuration {role_id!r} is not in the approved list "
                f"({', '.join(sorted(catalogue.by_id))})"
            )
    catalogue = catalogue.model_copy(
        update={"roles": RoleDefaults(retrieval=retrieval_id, structuring=structuring_id)}
    )
    sink = ListSink()
    meter = UsageMeter(prices, settings.eur_per_usd, sink)
    backend = Backend(
        False,
        catalogue,
        catalogue.by_id[structuring_id],
        catalogue.by_id[retrieval_id],
        meter,
        sink,
        env,
    )
    # Refused before any case runs: unknown, disabled or unverified configuration, missing key.
    backend.providers().check_ready()  # ProvidersNotReady names settings and configurations only
    return backend


def total_cost(sink: ListSink) -> Decimal:
    return sum((entry.cost for entry in sink.entries), Decimal(0))

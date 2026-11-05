"""Resolution: which configuration a call uses, and the checks made before any network call.

`Providers.structuring()` and `Providers.retrieval()` return a client bound to one configuration:
the one selected for the role by configuration (the file's `roles`), or the one a caller names
(a run reuses the configuration it recorded). The configuration must exist, support the role, be
`enabled` and have `verified_at` set, and its key setting must be set; otherwise the call is
refused before any adapter is built, and no other configuration is tried.
"""

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.limits.budget import BudgetGate
from app.providers.catalogue import (
    ROLES,
    ProviderCatalogue,
    ProviderConfigSpec,
    ProviderName,
    Role,
)
from app.providers.errors import (
    ProviderConfigurationRefused,
    ProviderError,
    ProviderSettingMissing,
    ProvidersNotReady,
)
from app.providers.interface import (
    RetrievalAdapter,
    RetrievalClient,
    StructuringAdapter,
    StructuringClient,
)
from app.providers.metering import UsageMeter

logger = logging.getLogger(__name__)

StructuringFactory = Callable[[ProviderConfigSpec, str], StructuringAdapter]
RetrievalFactory = Callable[[ProviderConfigSpec, str], RetrievalAdapter]


@dataclass(frozen=True)
class AdapterFactories:
    """How to build the adapter of one (provider, api) pair for each role it supports.

    A factory receives the configuration and the API key; the key goes to the vendor SDK client
    and nowhere else.
    """

    structuring: StructuringFactory | None = None
    retrieval: RetrievalFactory | None = None


AdapterTable = Mapping[tuple[ProviderName, str], AdapterFactories]


def default_adapters() -> AdapterTable:
    # Imported here so that `app.providers` loads without importing every vendor SDK up front.
    from app.providers.adapters import ADAPTERS

    return ADAPTERS


class Providers:
    def __init__(
        self,
        catalogue: ProviderCatalogue,
        environ: Mapping[str, str] | None = None,
        adapters: AdapterTable | None = None,
        *,
        meter: UsageMeter,
        budget: BudgetGate | None = None,
    ) -> None:
        self.catalogue = catalogue
        self._meter = meter
        # The per-run cost budget (#30): checked before every attempt of a run. Always given in
        # production (`app.main.load_providers`); the tests of other features may leave it out.
        self.budget = budget
        self._environ = os.environ if environ is None else environ
        self._adapters = adapters

    def selected(self, role: Role) -> str:
        """The configuration id used for `role` (the configuration default; #49 adds a choice)."""
        return self.catalogue.default_for(role)

    def resolve(self, role: Role, config_id: str | None = None) -> ProviderConfigSpec:
        """The approved configuration for `role`, or ProviderConfigurationRefused."""
        config_id = config_id or self.selected(role)
        config = self.catalogue.by_id.get(config_id)
        if config is None:
            raise ProviderConfigurationRefused(
                provider=None,
                config_id=config_id,
                reason="this configuration is not in the approved list; no other is tried.",
            )
        reason = None
        if role not in config.roles:
            reason = f"this configuration does not support the {role} role."
        elif not config.enabled:
            reason = "this configuration is disabled; no other is tried."
        elif config.verified_at is None:
            reason = "this configuration has not been verified, so it stays disabled."
        if reason is not None:
            raise ProviderConfigurationRefused(
                provider=config.provider, config_id=config.id, reason=reason
            )
        return config

    def _key(self, config: ProviderConfigSpec) -> str:
        value = self._environ.get(config.key_setting, "").strip()
        if not value:
            raise ProviderSettingMissing(
                provider=config.provider, config_id=config.id, setting=config.key_setting
            )
        return value

    def _factories(self, config: ProviderConfigSpec) -> AdapterFactories:
        adapters = self._adapters if self._adapters is not None else default_adapters()
        return adapters.get((config.provider, config.api), AdapterFactories())

    def _refused(self, config: ProviderConfigSpec, role: Role) -> ProviderConfigurationRefused:
        return ProviderConfigurationRefused(
            provider=config.provider,
            config_id=config.id,
            reason=f"no {role} adapter exists for this API.",
        )

    def structuring(self, config_id: str | None = None) -> StructuringClient:
        config = self.resolve("structuring", config_id)
        factory = self._factories(config).structuring
        if factory is None:
            raise self._refused(config, "structuring")
        return StructuringClient(
            config, factory(config, self._key(config)), self._meter, self.budget
        )

    def retrieval(self, config_id: str | None = None) -> RetrievalClient:
        config = self.resolve("retrieval", config_id)
        factory = self._factories(config).retrieval
        if factory is None:
            raise self._refused(config, "retrieval")
        return RetrievalClient(config, factory(config, self._key(config)), self._meter, self.budget)

    def missing_settings(self) -> list[str]:
        """Names (never values) of the key settings the selected configurations need and lack."""
        missing = set()
        for role in ROLES:
            config = self.catalogue.by_id.get(self.selected(role))
            if config is not None and not self._environ.get(config.key_setting, "").strip():
                missing.add(config.key_setting)
        return sorted(missing)

    def problems(self) -> list[ProviderError]:
        """Every reason why a run could not start with the selected configurations."""
        problems: list[ProviderError] = []
        for role in ROLES:
            try:
                config = self.resolve(role)
                self._key(config)
            except ProviderError as error:
                if all(str(error) != str(seen) for seen in problems):
                    problems.append(error)
        return problems

    def check_ready(self) -> None:
        """Run start (#13): raise ProvidersNotReady, naming settings and configurations only."""
        problems = self.problems()
        if problems:
            logger.warning("Providers not ready: %s", "; ".join(str(p) for p in problems))
            raise ProvidersNotReady(problems)

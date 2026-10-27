"""Registry settings, read from environment variables only (no file, no secret involved).

Kept apart from ``app.config`` so that the registries module stays self-contained.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from app.config import ConfigurationError

APPLICATION_NAME = "SupplierIScan"
APPLICATION_VERSION = "0.1.0"

# Public contact for registry operators (Wikimedia User-Agent policy: a URL or an e-mail address).
# The repository URL is the default; an instance sets REGISTRY_CONTACT to its own contact.
DEFAULT_CONTACT = "https://github.com/SPBONIFACE/supplier-iscan"
DEFAULT_CACHE_TTL_SECONDS = 86_400
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_GLEIF_REQUESTS_PER_MINUTE = 50
DEFAULT_WIKIDATA_MAX_PARALLEL = 5

# Spec, Integrations: GLEIF below 60 requests per minute; Wikidata at most 5 parallel queries.
GLEIF_REQUESTS_PER_MINUTE_LIMIT = 60
WIKIDATA_MAX_PARALLEL_LIMIT = 5


@dataclass(frozen=True)
class RegistrySettings:
    contact: str = DEFAULT_CONTACT
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    gleif_requests_per_minute: int = DEFAULT_GLEIF_REQUESTS_PER_MINUTE
    wikidata_max_parallel: int = DEFAULT_WIKIDATA_MAX_PARALLEL

    def __post_init__(self) -> None:
        if not self.contact.strip():
            raise ConfigurationError("REGISTRY_CONTACT must not be empty")
        if any(char in self.contact for char in "()\r\n"):
            raise ConfigurationError("REGISTRY_CONTACT must not contain parentheses or line breaks")
        if self.cache_ttl_seconds <= 0:
            raise ConfigurationError("REGISTRY_CACHE_TTL_SECONDS must be a positive number")
        if self.timeout_seconds <= 0:
            raise ConfigurationError("REGISTRY_TIMEOUT_SECONDS must be a positive number")
        if not 1 <= self.gleif_requests_per_minute < GLEIF_REQUESTS_PER_MINUTE_LIMIT:
            raise ConfigurationError("GLEIF_REQUESTS_PER_MINUTE must be between 1 and 59")
        if not 1 <= self.wikidata_max_parallel <= WIKIDATA_MAX_PARALLEL_LIMIT:
            raise ConfigurationError("WIKIDATA_MAX_PARALLEL must be between 1 and 5")

    @property
    def user_agent(self) -> str:
        # Wikimedia User-Agent policy format: name/version (contact; purpose).
        return (
            f"{APPLICATION_NAME}/{APPLICATION_VERSION} "
            f"({self.contact.strip()}; supplier identity search)"
        )


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number") from error


def load_registry_settings(environ: Mapping[str, str] | None = None) -> RegistrySettings:
    env = os.environ if environ is None else environ
    return RegistrySettings(
        contact=env.get("REGISTRY_CONTACT", "").strip() or DEFAULT_CONTACT,
        cache_ttl_seconds=_int(env, "REGISTRY_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS),
        timeout_seconds=_float(env, "REGISTRY_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        gleif_requests_per_minute=_int(
            env, "GLEIF_REQUESTS_PER_MINUTE", DEFAULT_GLEIF_REQUESTS_PER_MINUTE
        ),
        wikidata_max_parallel=_int(env, "WIKIDATA_MAX_PARALLEL", DEFAULT_WIKIDATA_MAX_PARALLEL),
    )

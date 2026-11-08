"""Approved provider configurations, loaded from a JSON file at startup (spec F6, Data model).

One record per exact API, model ID, endpoint, training setting, retention, region and transfer
mechanism. A record can be used only when it is `enabled` and has `verified_at` set; a record with
an unverified point stays disabled. The file also says which configuration each role uses by
default (#49 later lets the administrator choose among the approved ones).

The file named by PROVIDER_CONFIG_FILE is used; without that setting, the example shipped with the
application (`provider_configs.example.json`, every record disabled and unverified) is used. A
missing or invalid file stops startup with an error naming the file and the failing field.

No API key is ever in this file: keys are read from environment settings by name (`KEY_SETTINGS`).
"""

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from app.config import ConfigurationError

ProviderName = Literal["anthropic", "google", "openai", "mistral", "perplexity"]
PROVIDER_NAMES: tuple[ProviderName, ...] = (
    "anthropic",
    "google",
    "openai",
    "mistral",
    "perplexity",
)

Role = Literal["retrieval", "structuring"]
ROLES: tuple[Role, ...] = ("retrieval", "structuring")

# The API key of each provider, read from the environment by this name (and `.env.example`).
KEY_SETTINGS: dict[ProviderName, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
}

# The APIs an adapter exists for, and the roles each one can serve. `api` names the exact vendor
# API a configuration uses; the endpoint is the base URL the vendor SDK calls.
PROVIDER_APIS: dict[tuple[ProviderName, str], frozenset[Role]] = {
    ("anthropic", "messages"): frozenset({"structuring", "retrieval"}),
    ("google", "generate_content"): frozenset({"structuring", "retrieval"}),
    ("openai", "responses"): frozenset({"structuring", "retrieval"}),
    ("mistral", "chat_completions"): frozenset({"structuring"}),
    ("mistral", "conversations"): frozenset({"retrieval"}),
    ("perplexity", "agent"): frozenset({"structuring", "retrieval"}),
}

EXAMPLE_FILE = Path(__file__).resolve().parent / "provider_configs.example.json"
MAX_FILE_BYTES = 1_000_000


def _https_endpoint(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("must be an https URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("must not contain credentials, a query or a fragment")
    return value.rstrip("/")


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.utcoffset() is None:
        raise ValueError("must include a time zone (for example 2026-10-27T00:00:00Z)")
    return value


Text = Annotated[str, Field(min_length=1, max_length=200)]


class ProviderConfigSpec(BaseModel):
    """One approved provider configuration (spec, Data model: ProviderConfig)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,99}$")
    provider: ProviderName
    api: Text
    model_id: Text
    endpoint: Annotated[str, Field(max_length=500), AfterValidator(_https_endpoint)]
    training_setting: Text
    retention: Text
    region: Text
    transfer_mechanism: Text
    verified_at: Annotated[datetime | None, AfterValidator(_aware)]
    enabled: bool

    @model_validator(mode="after")
    def _known_api(self) -> "ProviderConfigSpec":
        if (self.provider, self.api) not in PROVIDER_APIS:
            known = sorted(api for provider, api in PROVIDER_APIS if provider == self.provider)
            raise ValueError(f"api must be one of {known} for provider {self.provider}")
        return self

    @property
    def roles(self) -> frozenset[Role]:
        return PROVIDER_APIS[(self.provider, self.api)]

    @property
    def key_setting(self) -> str:
        return KEY_SETTINGS[self.provider]

    @property
    def approved(self) -> bool:
        """Enabled and verified: the only state in which a call may be made."""
        return self.enabled and self.verified_at is not None


class RoleDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    retrieval: str
    structuring: str


class ProviderCatalogue(BaseModel):
    """The whole file: every configuration, and the configuration each role uses by default."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_configs: list[ProviderConfigSpec] = Field(min_length=1)
    roles: RoleDefaults

    @model_validator(mode="after")
    def _consistent(self) -> "ProviderCatalogue":
        ids = [config.id for config in self.provider_configs]
        duplicates = sorted({config_id for config_id in ids if ids.count(config_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate configuration id: {', '.join(duplicates)}")
        by_id = {config.id: config for config in self.provider_configs}
        for role in ROLES:
            config_id = getattr(self.roles, role)
            if config_id not in by_id:
                raise ValueError(f"roles.{role} names an unknown configuration {config_id!r}")
            if role not in by_id[config_id].roles:
                raise ValueError(
                    f"roles.{role}: configuration {config_id!r} does not support this role"
                )
        return self

    @property
    def by_id(self) -> Mapping[str, ProviderConfigSpec]:
        return {config.id: config for config in self.provider_configs}

    def default_for(self, role: Role) -> str:
        config_id: str = getattr(self.roles, role)
        return config_id


def _location(error: ValidationError) -> str:
    first = error.errors()[0]
    path = ".".join(str(part) for part in first.get("loc", ())) or "(file)"
    return f"{path}: {first.get('msg', 'invalid')}"


def load_catalogue(path: Path | None = None) -> ProviderCatalogue:
    """Read and validate the file. Raises ConfigurationError naming the file and the problem."""
    path = path or EXAMPLE_FILE
    label = f"Provider configuration file {path}"
    try:
        raw = path.read_bytes()
    except OSError:
        raise ConfigurationError(f"{label} cannot be read") from None
    if len(raw) > MAX_FILE_BYTES:
        raise ConfigurationError(f"{label} is larger than {MAX_FILE_BYTES} bytes")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"{label} is not valid JSON ({type(error).__name__})") from None
    if isinstance(document, dict):
        document.pop("$comment", None)
    try:
        return ProviderCatalogue.model_validate(document)
    except ValidationError as error:
        raise ConfigurationError(f"{label} is not valid: {_location(error)}") from None

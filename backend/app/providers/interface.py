"""The two provider interfaces, one per role, and the clients that feature code calls.

- Structuring (`StructuringClient.structure`): instructions and delimited data in, an instance of a
  typed pydantic schema out. The adapter asks the provider for JSON constrained by the schema
  (its structured-output mode); the client validates that JSON against the schema. Nothing is ever
  parsed out of free text. A schema failure is retried once, then raised as
  `StructuredOutputInvalid`.
- Retrieval (`RetrievalClient.retrieve`): a query in, the URLs the provider cited out, read from
  the provider's typed citation or search-result fields, never from its answer text.

Each client is bound to exactly one approved configuration (see `app.providers.registry`): it has
no list of alternatives, so a failure is raised to the caller and never falls back to another
provider. Prompts come from #55 and are passed in as text; the redaction gate (#19) sits in front.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.providers.catalogue import ProviderConfigSpec
from app.providers.errors import ProviderCallError, ProviderError, StructuredOutputInvalid
from app.providers.failures import classify_failure

logger = logging.getLogger(__name__)

# One retry after a schema failure (spec, Integrations: "retry once").
STRUCTURING_ATTEMPTS = 2
DEFAULT_MAX_OUTPUT_TOKENS = 8192


@dataclass(frozen=True)
class StructuringRequest:
    """`instructions` come from the prompt set (#55); `data` is the delimited data part."""

    instructions: str
    data: str
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS


@dataclass(frozen=True)
class RetrievalRequest:
    instructions: str
    query: str
    max_results: int = 10


class RetrievedUrl(BaseModel):
    """A URL the provider cited. The snippet is used only to rank; it is never shown as a fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1, max_length=4096)
    snippet: str = Field(default="", max_length=4000)


class RetrievalResult(BaseModel):
    """spec § LLM features: `RetrievalResult {urls: [{url, snippet}]}`. #20 verifies each URL."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    urls: list[RetrievedUrl]


class StructuringAdapter(Protocol):
    """One provider's structured-output call. Returns the JSON text of the structured output."""

    def generate_json(
        self, request: StructuringRequest, schema_name: str, json_schema: dict[str, object]
    ) -> str: ...


class RetrievalAdapter(Protocol):
    """One provider's search call. Returns the cited URLs from the provider's typed fields."""

    def search(self, request: RetrievalRequest) -> list[RetrievedUrl]: ...


def _call_failure(config: ProviderConfigSpec, error: Exception) -> ProviderError:
    if isinstance(error, ProviderError):
        return error
    kind, status_code = classify_failure(error)
    # The type and status only: an SDK message can quote the request or the response body.
    logger.warning(
        "Provider call failed: provider=%s configuration=%s kind=%s status=%s error=%s",
        config.provider,
        config.id,
        kind,
        status_code,
        type(error).__name__,
    )
    return ProviderCallError(
        provider=config.provider, config_id=config.id, kind=kind, status_code=status_code
    )


class _BoundClient:
    def __init__(self, config: ProviderConfigSpec) -> None:
        self.config = config

    @property
    def config_id(self) -> str:
        return self.config.id

    @property
    def provider(self) -> str:
        return self.config.provider

    @property
    def model_id(self) -> str:
        return self.config.model_id


class StructuringClient(_BoundClient):
    def __init__(self, config: ProviderConfigSpec, adapter: StructuringAdapter) -> None:
        super().__init__(config)
        self._adapter = adapter

    def structure[T: BaseModel](self, request: StructuringRequest, output_type: type[T]) -> T:
        schema_name = output_type.__name__
        json_schema = output_type.model_json_schema()
        for attempt in range(1, STRUCTURING_ATTEMPTS + 1):
            failure: ProviderError | None = None
            try:
                text = self._adapter.generate_json(request, schema_name, json_schema)
            except Exception as error:  # noqa: BLE001 - every failure becomes a typed error
                failure = _call_failure(self.config, error)
            if failure is not None:
                # Raised outside the `except` block, so the SDK exception (which holds the
                # request, headers included) is not chained to it.
                raise failure
            try:
                return output_type.model_validate_json(text)
            except ValidationError as error:
                # Counts only: the output itself is never logged.
                logger.warning(
                    "Structured output rejected: provider=%s configuration=%s schema=%s "
                    "attempt=%d errors=%d",
                    self.config.provider,
                    self.config.id,
                    schema_name,
                    attempt,
                    error.error_count(),
                )
        raise StructuredOutputInvalid(
            provider=self.config.provider,
            config_id=self.config.id,
            schema_name=schema_name,
            attempts=STRUCTURING_ATTEMPTS,
        )


class RetrievalClient(_BoundClient):
    def __init__(self, config: ProviderConfigSpec, adapter: RetrievalAdapter) -> None:
        super().__init__(config)
        self._adapter = adapter

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        failure: ProviderError | None = None
        try:
            urls = self._adapter.search(request)
        except Exception as error:  # noqa: BLE001 - every failure becomes a typed error
            failure = _call_failure(self.config, error)
        if failure is not None:
            raise failure
        unique: dict[str, RetrievedUrl] = {}
        for item in urls:
            unique.setdefault(item.url, item)
        return RetrievalResult(urls=list(unique.values())[: request.max_results])

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
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.limits.budget import BudgetGate
from app.providers.catalogue import ProviderConfigSpec, Role
from app.providers.errors import ProviderCallError, ProviderError, StructuredOutputInvalid
from app.providers.failures import classify_failure
from app.providers.metering import NO_USAGE, CallContext, CallUsage, Outcome, UsageMeter
from app.redaction.text import RedactedText
from app.telemetry import record_failure, span

logger = logging.getLogger(__name__)

# One retry after a schema failure (spec, Integrations: "retry once"): the default of the
# configured maximum (PROVIDER_MAX_RETRIES). Every attempt is metered and counts against the run
# budget (#30).
DEFAULT_MAX_RETRIES = 1
DEFAULT_MAX_OUTPUT_TOKENS = 8192
# What a retrieval attempt can consume, for the budget check: the largest output allowance and
# number of search calls of an adapter (the Anthropic one: 2048 tokens, 5 searches).
RETRIEVAL_MAX_OUTPUT_TOKENS = 2048
RETRIEVAL_MAX_TOOL_CALLS = 5


def _require_redacted(value: object) -> None:
    if not isinstance(value, RedactedText):
        # The type only: the value is raw text and is never put in a message.
        raise TypeError(
            f"a provider takes only text that passed the redaction gate, not {type(value).__name__}"
        )


@dataclass(frozen=True)
class StructuringRequest:
    """`instructions` come from the prompt set (#55) and hold no member data; `data` is the
    delimited data part, redacted (#19)."""

    instructions: str
    data: RedactedText
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS

    def __post_init__(self) -> None:
        _require_redacted(self.data)


@dataclass(frozen=True)
class RetrievalRequest:
    instructions: str
    query: RedactedText
    max_results: int = 10

    def __post_init__(self) -> None:
        _require_redacted(self.query)


class RetrievedUrl(BaseModel):
    """A URL the provider cited. The snippet is used only to rank; it is never shown as a fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1, max_length=4096)
    snippet: str = Field(default="", max_length=4000)


class RetrievalResult(BaseModel):
    """spec § LLM features: `RetrievalResult {urls: [{url, snippet}]}`. #20 verifies each URL."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    urls: list[RetrievedUrl]


@dataclass(frozen=True)
class StructuringOutput:
    """The JSON text of the structured output, and what the call consumed (#12)."""

    text: str
    usage: CallUsage = NO_USAGE


@dataclass(frozen=True)
class RetrievalOutput:
    urls: list[RetrievedUrl]
    usage: CallUsage = NO_USAGE


class StructuringAdapter(Protocol):
    """One provider's structured-output call."""

    def generate_json(
        self, request: StructuringRequest, schema_name: str, json_schema: dict[str, object]
    ) -> StructuringOutput: ...


class RetrievalAdapter(Protocol):
    """One provider's search call. The URLs come from the provider's typed fields."""

    def search(self, request: RetrievalRequest) -> RetrievalOutput: ...


def _call_failure(config: ProviderConfigSpec, error: Exception) -> ProviderError:
    if isinstance(error, ProviderError):
        return error
    kind, status_code = classify_failure(error)
    # An event on the call's span: the kind and the error type, never the SDK's message.
    record_failure(type(error).__name__, {"iscan.failure_kind": kind})
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
    role: Role

    def __init__(
        self, config: ProviderConfigSpec, meter: UsageMeter, budget: BudgetGate | None = None
    ) -> None:
        self.config = config
        self._meter = meter
        self._budget = budget
        # Refused before any call when the model has no price: it is never metered as free.
        meter.require_price(config)

    @property
    def max_retries(self) -> int:
        """The most retries of one call after a schema failure (configuration, #30)."""
        return self._budget.max_retries if self._budget is not None else DEFAULT_MAX_RETRIES

    def _check_budget(
        self, context: CallContext, input_chars: int, output_tokens: int, tool_calls: int
    ) -> None:
        """Before every attempt of a run: raises RunBudgetExhausted when the run's billed cost
        plus the most this attempt can cost is above the run budget. The call is then not made.
        A call outside a run (the identity chat) has no run budget."""
        if self._budget is None or context.run_id is None:
            return
        estimate = self._meter.max_call_cost(self.config, input_chars, output_tokens, tool_calls)
        self._budget.check(context.organisation_id, context.run_id, estimate)

    @property
    def config_id(self) -> str:
        return self.config.id

    @property
    def provider(self) -> str:
        return self.config.provider

    @property
    def model_id(self) -> str:
        return self.config.model_id

    def _call_span(self, attempt: int) -> Any:
        """The span of one provider call: identifiers only, never the prompt or the response."""
        return span(
            "provider.call",
            {
                "iscan.provider": self.config.provider,
                "iscan.provider_config": self.config.id,
                "iscan.model_id": self.config.model_id,
                "iscan.role": self.role,
                "iscan.attempt": attempt,
            },
        )

    def _record(
        self, context: CallContext, attempt: int, outcome: Outcome, usage: CallUsage
    ) -> None:
        self._meter.record(self.config, self.role, context, attempt, outcome, usage)


class StructuringClient(_BoundClient):
    role: Role = "structuring"

    def __init__(
        self,
        config: ProviderConfigSpec,
        adapter: StructuringAdapter,
        meter: UsageMeter,
        budget: BudgetGate | None = None,
    ) -> None:
        super().__init__(config, meter, budget)
        self._adapter = adapter

    def structure[T: BaseModel](
        self, request: StructuringRequest, output_type: type[T], context: CallContext
    ) -> T:
        _require_redacted(request.data)  # a request edited after its creation is refused too
        schema_name = output_type.__name__
        json_schema = output_type.model_json_schema()
        attempts = 1 + self.max_retries
        input_chars = len(request.instructions) + len(request.data.text)
        for attempt in range(1, attempts + 1):
            failure: ProviderError | None = None
            output: StructuringOutput | None = None
            self._check_budget(context, input_chars, request.max_output_tokens, 0)
            with self._call_span(attempt):
                try:
                    output = self._adapter.generate_json(request, schema_name, json_schema)
                except Exception as error:  # noqa: BLE001 - every failure becomes a typed error
                    failure = _call_failure(self.config, error)
            if failure is not None:
                # Every attempt is metered, a failed one too.
                self._record(context, attempt, "failed", NO_USAGE)
                # Raised outside the `except` block, so the SDK exception (which holds the
                # request, headers included) is not chained to it.
                raise failure
            if output is None:
                raise AssertionError("unreachable: no output and no failure")
            try:
                result = output_type.model_validate_json(output.text)
            except ValidationError as error:
                # The call succeeded and consumed tokens: metered although its output is dropped.
                self._record(context, attempt, "invalid_output", output.usage)
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
                continue
            self._record(context, attempt, "success", output.usage)
            return result
        raise StructuredOutputInvalid(
            provider=self.config.provider,
            config_id=self.config.id,
            schema_name=schema_name,
            attempts=attempts,
        )


class RetrievalClient(_BoundClient):
    role: Role = "retrieval"

    def __init__(
        self,
        config: ProviderConfigSpec,
        adapter: RetrievalAdapter,
        meter: UsageMeter,
        budget: BudgetGate | None = None,
    ) -> None:
        super().__init__(config, meter, budget)
        self._adapter = adapter

    def retrieve(self, request: RetrievalRequest, context: CallContext) -> RetrievalResult:
        _require_redacted(request.query)
        failure: ProviderError | None = None
        output: RetrievalOutput | None = None
        self._check_budget(
            context,
            len(request.instructions) + len(request.query.text),
            RETRIEVAL_MAX_OUTPUT_TOKENS,
            RETRIEVAL_MAX_TOOL_CALLS,
        )
        with self._call_span(1):
            try:
                output = self._adapter.search(request)
            except Exception as error:  # noqa: BLE001 - every failure becomes a typed error
                failure = _call_failure(self.config, error)
        if failure is not None:
            self._record(context, 1, "failed", NO_USAGE)
            raise failure
        if output is None:
            raise AssertionError("unreachable: no output and no failure")
        self._record(context, 1, "success", output.usage)
        unique: dict[str, RetrievedUrl] = {}
        for item in output.urls:
            unique.setdefault(item.url, item)
        return RetrievalResult(urls=list(unique.values())[: request.max_results])

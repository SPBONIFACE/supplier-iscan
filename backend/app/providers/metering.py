"""Metering (spec F6/F7, #12): one usage record for every provider call attempt.

Every attempt counts: a call that fails, a call whose output fails the schema (it consumed
tokens), a retry, a search tool, reasoning tokens. The client calls `UsageMeter.record` after each
attempt; the record goes to a `UsageSink` (the database in production, a list in tests). A record
holds counts, identifiers and the cost; it never holds the prompt or the response text.

Cost: the amount the provider reports as billed when it does (Perplexity), otherwise tokens and
tool calls times the price table. It is kept in the currency the provider bills in, then converted
to EUR with the configured rate, and the record stores the rate it used. A model without a price
entry is refused before the call (`UsageMeter.require_price`), so no call is metered as free.
`output_tokens` never includes `reasoning_tokens` (adapters subtract them), so nothing is counted
twice.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Protocol

from app.config import EUR_PER_USD, ConfigurationError
from app.db import utc_now
from app.providers.catalogue import ProviderConfigSpec, Role
from app.providers.errors import ProviderConfigurationRefused
from app.providers.pricing import PriceEntry, PriceTable

Outcome = Literal["success", "invalid_output", "failed"]
CostBasis = Literal["provider", "price_table", "unreported"]

_MILLION = Decimal(1_000_000)
_EIGHT_PLACES = Decimal("0.00000001")


@dataclass(frozen=True)
class CallUsage:
    """What one provider response says it consumed. `reported` is False when it said nothing."""

    input_tokens: int = 0
    output_tokens: int = 0  # without reasoning tokens
    reasoning_tokens: int = 0
    tool_calls: int = 0
    billed_amount: Decimal | None = None
    billed_currency: str | None = None
    reported: bool = True


NO_USAGE = CallUsage(reported=False)


@dataclass(frozen=True)
class CallContext:
    """Who a call is for. `attempt_offset` numbers a run's own retries after the client's own."""

    organisation_id: uuid.UUID
    run_id: uuid.UUID | None = None
    attempt_offset: int = 0


@dataclass(frozen=True)
class UsageEntry:
    """One row of `llm_usage`. No prompt, no response."""

    organisation_id: uuid.UUID
    run_id: uuid.UUID | None
    provider_config_id: str
    provider: str
    model_id: str
    role: Role
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    tool_calls: int
    attempt: int
    outcome: Outcome
    billed_amount: Decimal
    billed_currency: str
    exchange_rate: Decimal
    cost: Decimal  # EUR
    cost_basis: CostBasis
    price_as_of: date | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=utc_now)


class UsageSink(Protocol):
    def record(self, entry: UsageEntry) -> None: ...


class UsageMeter:
    def __init__(self, prices: PriceTable, eur_per_usd: Decimal | None, sink: UsageSink) -> None:
        self._prices = prices
        self._eur_per_usd = eur_per_usd
        self._sink = sink

    def require_price(self, config: ProviderConfigSpec) -> PriceEntry:
        entry = self._prices.find(config.provider, config.model_id)
        if entry is None:
            raise ProviderConfigurationRefused(
                provider=config.provider,
                config_id=config.id,
                reason=(
                    f"the price table has no entry for model {config.model_id!r}; "
                    "the call is refused so that it is never metered as free."
                ),
            )
        return entry

    def _rate(self, currency: str) -> Decimal:
        if currency == "EUR":
            return Decimal(1)
        if currency == "USD" and self._eur_per_usd is not None:
            return self._eur_per_usd
        raise ConfigurationError(f"{EUR_PER_USD} must be set to convert {currency} costs to EUR")

    def record(
        self,
        config: ProviderConfigSpec,
        role: Role,
        context: CallContext,
        attempt: int,
        outcome: Outcome,
        usage: CallUsage,
    ) -> UsageEntry:
        price = self.require_price(config)
        if usage.billed_amount is not None:
            amount = usage.billed_amount
            currency = usage.billed_currency or price.currency
            basis: CostBasis = "provider"
            as_of: date | None = None
        else:
            amount = (
                usage.input_tokens * price.input_per_million
                + usage.output_tokens * price.output_per_million
                + usage.reasoning_tokens * (price.reasoning_per_million or price.output_per_million)
            ) / _MILLION + usage.tool_calls * price.tool_call
            currency = price.currency
            basis = "price_table" if usage.reported else "unreported"
            as_of = price.as_of
        rate = self._rate(currency)
        entry = UsageEntry(
            organisation_id=context.organisation_id,
            run_id=context.run_id,
            provider_config_id=config.id,
            provider=config.provider,
            model_id=config.model_id,
            role=role,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            tool_calls=usage.tool_calls,
            attempt=context.attempt_offset + attempt,
            outcome=outcome,
            billed_amount=amount.quantize(_EIGHT_PLACES, ROUND_HALF_UP),
            billed_currency=currency,
            exchange_rate=rate,
            cost=(amount * rate).quantize(_EIGHT_PLACES, ROUND_HALF_UP),
            cost_basis=basis,
            price_as_of=as_of,
        )
        self._sink.record(entry)
        return entry


@dataclass
class ListSink:
    """Keeps the entries in memory (tests)."""

    entries: list[UsageEntry] = field(default_factory=list)

    def record(self, entry: UsageEntry) -> None:
        self.entries.append(entry)

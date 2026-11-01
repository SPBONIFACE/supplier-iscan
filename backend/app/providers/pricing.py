"""The price table: what each approved model costs (spec F6/F7, #12).

Prices are configuration, never code: a JSON file named by PRICE_TABLE_FILE (the shipped
`price_table.example.json` otherwise), one entry per provider and model ID, each with an "as of"
date and the currency the provider bills in. Amounts are per million tokens, and per search or
tool call. A reasoning-token price is optional (reasoning tokens are billed as output when absent).

An approved configuration whose model has no entry stops startup (`check_prices`), so that no call
is ever metered as free. Costs are shown in EUR: USD prices are converted with the configured
rate EUR_PER_USD (a setting), and each usage record keeps the rate it used.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.config import EUR_PER_USD, ConfigurationError
from app.providers.catalogue import ProviderCatalogue, ProviderName

EXAMPLE_PRICE_FILE = Path(__file__).resolve().parent / "price_table.example.json"
MAX_FILE_BYTES = 1_000_000

Amount = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=8)]


class PriceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    model_id: str = Field(min_length=1, max_length=200)
    currency: Literal["USD", "EUR"]
    as_of: date
    input_per_million: Amount
    output_per_million: Amount
    reasoning_per_million: Amount | None = None
    # One search or tool call; write "0" explicitly when the provider charges nothing for it.
    tool_call: Amount


class PriceTable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prices: list[PriceEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> "PriceTable":
        keys = [(entry.provider, entry.model_id) for entry in self.prices]
        duplicates = sorted({f"{p}/{m}" for p, m in keys if keys.count((p, m)) > 1})
        if duplicates:
            raise ValueError(f"duplicate price entry: {', '.join(duplicates)}")
        return self

    def find(self, provider: str, model_id: str) -> PriceEntry | None:
        for entry in self.prices:
            if (entry.provider, entry.model_id) == (provider, model_id):
                return entry
        return None


def load_price_table(path: Path | None = None) -> PriceTable:
    path = path or EXAMPLE_PRICE_FILE
    label = f"Price table file {path}"
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
        return PriceTable.model_validate(document)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first.get("loc", ())) or "(file)"
        raise ConfigurationError(f"{label} is not valid: {where}: {first.get('msg')}") from None


def check_prices(
    catalogue: ProviderCatalogue, table: PriceTable, eur_per_usd: Decimal | None
) -> None:
    """Startup: every approved configuration has a price, and USD prices have a rate."""
    for config in catalogue.provider_configs:
        if not config.approved:
            continue
        entry = table.find(config.provider, config.model_id)
        if entry is None:
            raise ConfigurationError(
                f"The price table has no entry for model {config.model_id!r} of provider "
                f"{config.provider} (configuration {config.id!r}): add its prices, so that "
                "no call is metered as free"
            )
        if entry.currency == "USD" and eur_per_usd is None:
            raise ConfigurationError(
                f"{EUR_PER_USD} must be set: model {config.model_id!r} is priced in USD "
                "and costs are shown in EUR"
            )

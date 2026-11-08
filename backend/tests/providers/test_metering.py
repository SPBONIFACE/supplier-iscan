"""Usage and cost per call (#12): every attempt is metered, costs come from the price table."""

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.config import ConfigurationError, Settings, load_settings
from app.db import Database
from app.main import create_app
from app.models import LlmUsage, Organisation
from app.providers import Providers
from app.providers.catalogue import ProviderCatalogue
from app.providers.errors import ProviderCallError, ProviderConfigurationRefused
from app.providers.fake import FakeRetrievalAdapter, FakeStructuringAdapter, fake_adapters
from app.providers.interface import (
    RetrievalOutput,
    RetrievalRequest,
    RetrievedUrl,
    StructuringOutput,
    StructuringRequest,
)
from app.providers.metering import NO_USAGE, CallContext, CallUsage, ListSink, UsageMeter
from app.providers.pricing import PriceTable, check_prices, load_price_table
from app.providers.store import sync_provider_configs
from app.providers.usage import DbUsageSink, run_usage_totals
from tests.factories import create_organisation
from tests.providers.support import (
    CONTEXT,
    EUR_PER_USD,
    PRICES,
    SENTINEL_KEY,
    Company,
    catalogue,
    config,
    make_meter,
)
from tests.redacted import redacted
from tests.runs_support import create_run
from tests.support import LOCAL_ORIGIN

GOOD = '{"legal_name": "Acme SA", "country": "FR"}'
BAD = '{"legal_name": 7}'
REQUEST = StructuringRequest(
    instructions="SECRET-INSTRUCTIONS", data=redacted("SECRET-DATA Acme SA")
)
ENV = {"GEMINI_API_KEY": SENTINEL_KEY, "ANTHROPIC_API_KEY": SENTINEL_KEY}


def providers_with(
    sink: ListSink | DbUsageSink,
    structuring: FakeStructuringAdapter | None = None,
    retrieval: FakeRetrievalAdapter | None = None,
    cat: ProviderCatalogue | None = None,
) -> Providers:
    cat = cat or catalogue(config("primary"))
    meter = UsageMeter(PRICES, EUR_PER_USD, sink)
    return Providers(cat, ENV, fake_adapters(cat, structuring, retrieval), meter=meter)


def test_the_cost_is_tokens_and_tool_calls_times_the_price_converted_to_eur() -> None:
    sink = ListSink()
    usage = CallUsage(input_tokens=1000, output_tokens=500, reasoning_tokens=250, tool_calls=2)

    entry = make_meter(sink).record(config("primary"), "structuring", CONTEXT, 1, "success", usage)

    # 1000 x 1.00/M + (500 + 250 reasoning, billed as output) x 4.00/M + 2 calls x 0.01 USD
    assert entry.billed_amount == Decimal("0.02400000") and entry.billed_currency == "USD"
    assert (entry.exchange_rate, entry.cost) == (EUR_PER_USD, Decimal("0.02160000"))
    assert (entry.cost_basis, str(entry.price_as_of)) == ("price_table", "2026-10-27")
    assert sink.entries == [entry]


def test_a_separate_reasoning_price_is_used_and_an_eur_price_needs_no_rate() -> None:
    table = PriceTable.model_validate(
        {
            "prices": [
                {
                    "provider": "google",
                    "model_id": "model-1",
                    "currency": "EUR",
                    "as_of": "2026-10-27",
                    "input_per_million": "1",
                    "output_per_million": "2",
                    "reasoning_per_million": "10",
                    "tool_call": "0",
                }
            ]
        }
    )
    meter = UsageMeter(table, None, ListSink())  # no rate configured

    entry = meter.record(
        config("primary"), "structuring", CONTEXT, 1, "success",
        CallUsage(input_tokens=1_000_000, output_tokens=1_000_000, reasoning_tokens=100_000),
    )  # fmt: skip

    assert entry.cost == Decimal("4.00000000") and entry.exchange_rate == 1


def test_the_amount_the_provider_billed_is_the_cost_when_it_reports_one() -> None:
    usage = CallUsage(
        input_tokens=1, output_tokens=1, billed_amount=Decimal("0.01"), billed_currency="USD"
    )

    entry = make_meter().record(config("primary"), "retrieval", CONTEXT, 1, "success", usage)

    assert (entry.cost_basis, entry.billed_amount) == ("provider", Decimal("0.01000000"))
    assert entry.cost == Decimal("0.00900000")


def test_a_response_without_usage_is_flagged_not_silently_free() -> None:
    entry = make_meter().record(config("primary"), "structuring", CONTEXT, 1, "failed", NO_USAGE)

    assert entry.cost == 0
    assert entry.cost_basis == "unreported"


def test_a_model_without_a_price_is_refused_before_any_call() -> None:
    fake = FakeStructuringAdapter([GOOD])
    cat = catalogue(config("primary", model_id="model-without-price"))

    with pytest.raises(ProviderConfigurationRefused, match="model-without-price"):
        providers_with(ListSink(), fake, cat=cat).structuring()

    assert fake.calls == []


def _write(
    tmp_path: Path, cat: ProviderCatalogue, prices: dict[str, Any] | None = None
) -> Settings:
    config_file = tmp_path / "configs.json"
    config_file.write_text(cat.model_dump_json(), encoding="utf-8")
    price_file = tmp_path / "prices.json"
    price_file.write_text(json.dumps(prices or {"prices": []}), encoding="utf-8")
    return Settings(
        database_url=None,
        allowed_origins=(LOCAL_ORIGIN,),
        provider_config_file=str(config_file),
        price_table_file=str(price_file) if prices else None,
        eur_per_usd=Decimal("0.9"),
        run_budget_eur=Decimal(5),
    )


def test_an_approved_configuration_without_a_price_stops_startup(tmp_path: Path) -> None:
    cat = catalogue(config("primary", model_id="gemini-9-ghost"))
    only_other_model = {"prices": [PRICES.prices[0].model_dump(mode="json")]}

    with pytest.raises(ConfigurationError, match="gemini-9-ghost"):
        create_app(_write(tmp_path, cat, only_other_model))


def test_a_disabled_configuration_needs_no_price(tmp_path: Path) -> None:
    cat = catalogue(config("primary", model_id="gemini-9-ghost", enabled=False))
    other = {"prices": [PRICES.prices[0].model_dump(mode="json")]}

    create_app(_write(tmp_path, cat, other))


def test_usd_prices_without_the_eur_rate_stop_startup() -> None:
    cat = catalogue(config("primary"))

    with pytest.raises(ConfigurationError, match="EUR_PER_USD"):
        check_prices(cat, PRICES, None)
    check_prices(cat, PRICES, Decimal("0.9"))


@pytest.mark.parametrize("raw", ["abc", "0", "-1", "1000", "nan"])
def test_the_rate_setting_is_validated(raw: str) -> None:
    with pytest.raises(ConfigurationError, match="EUR_PER_USD"):
        load_settings({"EUR_PER_USD": raw})
    assert load_settings({"EUR_PER_USD": "0.92"}).eur_per_usd == Decimal("0.92")
    assert load_settings({}).eur_per_usd is None


def test_the_shipped_price_table_is_valid_and_dated() -> None:
    table = load_price_table()

    assert all(entry.as_of.year >= 2026 for entry in table.prices)


def test_an_invalid_price_file_names_the_file_and_the_field(tmp_path: Path) -> None:
    path = tmp_path / "prices.json"
    path.write_text('{"prices": [{"provider": "google", "model_id": "m"}]}', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="prices.json is not valid: prices.0"):
        load_price_table(path)


def test_a_failed_attempt_and_its_retry_are_two_records_and_both_costs_count() -> None:
    sink = ListSink()
    usage = CallUsage(input_tokens=1000, output_tokens=500)
    fake = FakeStructuringAdapter([StructuringOutput(BAD, usage), StructuringOutput(GOOD, usage)])
    run = uuid.uuid4()

    client = providers_with(sink, fake).structuring()
    result = client.structure(REQUEST, Company, CallContext(CONTEXT.organisation_id, run))

    assert result == Company(legal_name="Acme SA", country="FR")
    assert [(e.attempt, e.outcome) for e in sink.entries] == [(1, "invalid_output"), (2, "success")]
    assert {e.run_id for e in sink.entries} == {run}
    assert sum(e.cost for e in sink.entries) == 2 * sink.entries[0].cost > 0


def test_a_call_that_raises_is_recorded_and_the_next_attempt_follows_it() -> None:
    sink = ListSink()
    usage = CallUsage(input_tokens=10, output_tokens=5)
    fake = FakeStructuringAdapter([RuntimeError("boom"), StructuringOutput(GOOD, usage)])
    client = providers_with(sink, fake).structuring()

    with pytest.raises(ProviderCallError):
        client.structure(REQUEST, Company, CONTEXT)
    client.structure(REQUEST, Company, CallContext(CONTEXT.organisation_id, attempt_offset=1))

    assert [(e.attempt, e.outcome) for e in sink.entries] == [(1, "failed"), (2, "success")]
    assert sink.entries[0].cost == 0 and sink.entries[1].cost > 0


def test_retrieval_is_metered_with_its_search_calls() -> None:
    sink = ListSink()
    urls = [RetrievedUrl(url="https://acme.example/a")]
    usage = CallUsage(input_tokens=100, output_tokens=50, tool_calls=3)
    fake = FakeRetrievalAdapter([RuntimeError("boom"), RetrievalOutput(urls, usage)])
    client = providers_with(sink, retrieval=fake).retrieval()
    request = RetrievalRequest(instructions="SECRET-INSTRUCTIONS", query=redacted("SECRET-QUERY"))

    with pytest.raises(ProviderCallError):
        client.retrieve(request, CONTEXT)
    client.retrieve(request, CONTEXT)

    assert [(e.role, e.outcome, e.tool_calls) for e in sink.entries] == [
        ("retrieval", "failed", 0),
        ("retrieval", "success", 3),
    ]


def test_a_record_never_holds_the_prompt_or_the_response() -> None:
    sink = ListSink()
    fake = FakeStructuringAdapter([StructuringOutput(GOOD, CallUsage(input_tokens=5))])

    providers_with(sink, fake).structuring().structure(REQUEST, Company, CONTEXT)

    text_of_record = repr(sink.entries)
    for secret in ("SECRET-INSTRUCTIONS", "SECRET-DATA", "Acme SA", SENTINEL_KEY):
        assert secret not in text_of_record
    columns = {column.name for column in LlmUsage.__table__.columns}
    assert not {"prompt", "response", "text", "content", "output", "input"} & columns


def test_run_totals_add_up_every_attempt_and_name_the_models_per_role(engine: Engine) -> None:
    organisation_id = create_organisation(engine)
    other_organisation = create_organisation(engine, "Other Buyers")
    cat = catalogue(
        config("primary"), config("searcher", "anthropic", "messages", model_id="model-2")
    )
    with Session(engine) as db:
        sync_provider_configs(db, cat)
    usage = CallUsage(input_tokens=1000, output_tokens=400, reasoning_tokens=100, tool_calls=1)
    structuring = FakeStructuringAdapter(
        [
            StructuringOutput(BAD, usage),
            StructuringOutput(GOOD, usage),
            StructuringOutput(GOOD, usage),
        ]
    )
    retrieval = FakeRetrievalAdapter(
        [RetrievalOutput([RetrievedUrl(url="https://acme.example/a")], usage)]
    )
    sink = DbUsageSink(Database(None, engine))
    providers = Providers(
        cat,
        ENV,
        fake_adapters(cat, structuring, retrieval),
        meter=UsageMeter(PRICES, EUR_PER_USD, sink),
    )
    run = create_run(engine, organisation_id, enqueue=False)
    other_run = create_run(engine, other_organisation, enqueue=False)

    providers.structuring("primary").structure(REQUEST, Company, CallContext(organisation_id, run))
    providers.retrieval("searcher").retrieve(
        RetrievalRequest(instructions="i", query=redacted("q")), CallContext(organisation_id, run)
    )
    providers.structuring("primary").structure(
        REQUEST, Company, CallContext(other_organisation, other_run)
    )

    with Session(engine) as db:
        totals = run_usage_totals(db, organisation_id, run)
        unknown = run_usage_totals(db, organisation_id, other_run)  # another organisation's run
        rows = db.scalars(select(LlmUsage).where(LlmUsage.run_id == run)).all()
        expected_cost = sum(row.cost for row in rows)

    assert totals.calls == 3  # the invalid output, its retry, the search
    assert (totals.input_tokens, totals.output_tokens) == (3000, 1200)
    assert (totals.reasoning_tokens, totals.tool_calls) == (300, 3)
    assert totals.cost == expected_cost > 0
    assert {
        role: [(m.config_id, m.provider, m.model_id) for m in models]
        for role, models in totals.roles.items()
    } == {
        "structuring": [("primary", "google", "model-1")],
        "retrieval": [("searcher", "anthropic", "model-2")],
    }
    assert unknown.calls == 0 and unknown.cost == 0 and unknown.roles == {}


def test_a_record_survives_the_callers_rollback_and_is_in_eur_with_its_rate(engine: Engine) -> None:
    organisation_id = create_organisation(engine)
    cat = catalogue(config("primary"))
    with Session(engine) as db:
        sync_provider_configs(db, cat)
    fake = FakeStructuringAdapter([StructuringOutput(GOOD, CallUsage(input_tokens=1_000_000))])
    providers = providers_with(DbUsageSink(Database(None, engine)), fake, cat=cat)

    with Session(engine) as caller:
        caller.add(Organisation(name="Rolled back"))
        providers.structuring().structure(REQUEST, Company, CallContext(organisation_id))
        caller.rollback()

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT cost, billed_amount, billed_currency, exchange_rate, run_id FROM llm_usage"
            )
        ).one()
    assert (row.billed_amount, row.billed_currency) == (Decimal("1.00000000"), "USD")
    assert (row.exchange_rate, row.cost, row.run_id) == (
        Decimal("0.90000000"),
        Decimal("0.90000000"),
        None,
    )

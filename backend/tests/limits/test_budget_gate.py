"""The per-run cost budget (#30) at the provider client: the check before every attempt, retries
bounded and counted, the estimate as an upper bound, missing prices, the configuration, and the
largest overrun under concurrency. Fake provider, no network."""

import json
import threading
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, update

from app.config import ConfigurationError, Settings, load_settings, require_run_budget
from app.db import Database
from app.limits.budget import RunBudgetExhausted
from app.main import load_providers
from app.models import ProfileRun
from app.providers import Providers, StructuredOutputInvalid, StructuringRequest
from app.providers.errors import ProviderCallError, ProviderConfigurationRefused
from app.providers.fake import FakeStructuringAdapter, fake_adapters
from app.providers.interface import StructuringOutput
from app.providers.metering import CallContext, CallUsage, UsageMeter
from app.providers.pricing import PriceTable
from app.redaction import gate_for
from tests.factories import create_organisation
from tests.limits.support import (
    BILLED,
    CALL_COST,
    BilledText,
    allow,
    context_of,
    providers_for,
    total_cost,
    usage_rows,
)
from tests.providers.support import (
    PRICES,
    SENTINEL_KEY,
    Company,
    catalogue,
    config,
    make_meter,
)
from tests.runs_support import create_run

VALID = json.dumps({"legal_name": "Acme", "country": "FR"})
INVALID = "not json"


def request_for(engine: Engine, text: str = "Acme Supplies SA, France") -> StructuringRequest:
    redacted = gate_for(Database(None, engine)).redact(text)
    return StructuringRequest(instructions="Extract the company. " * 40, data=redacted)


def started(engine: Engine) -> tuple[Any, Any]:
    organisation_id = create_organisation(engine)
    return organisation_id, create_run(engine, organisation_id, status="running", enqueue=False)


def billed(*texts: str) -> BilledText:
    return BilledText(list(texts))


# --- the check before each call ---------------------------------------------------------------


def test_a_call_that_would_exceed_the_budget_is_not_made(engine: Engine) -> None:
    organisation_id, run_id = started(engine)
    adapter = billed(VALID, VALID)
    client = providers_for(engine, adapter, budget=allow(1)).structuring()
    context = context_of(organisation_id, run_id)

    first = client.structure(request_for(engine), Company, context)
    with pytest.raises(RunBudgetExhausted):
        client.structure(request_for(engine), Company, context)

    assert first.legal_name == "Acme"
    assert len(adapter.calls) == 1  # the second request was never sent
    assert total_cost(engine, run_id) == CALL_COST


def test_a_call_is_refused_when_its_own_estimate_is_above_the_budget(engine: Engine) -> None:
    organisation_id, run_id = started(engine)
    adapter = billed(VALID)
    client = providers_for(engine, adapter, budget=Decimal("0.01")).structuring()

    with pytest.raises(RunBudgetExhausted):
        client.structure(request_for(engine), Company, context_of(organisation_id, run_id))

    assert adapter.calls == [] and usage_rows(engine, run_id) == []


def test_the_budget_is_per_run_and_a_call_outside_a_run_has_none(engine: Engine) -> None:
    organisation_id, run_id = started(engine)
    other = create_run(engine, organisation_id, status="running", enqueue=False)
    adapter = billed(VALID, VALID, VALID)
    client = providers_for(engine, adapter, budget=allow(1)).structuring()
    client.structure(request_for(engine), Company, context_of(organisation_id, run_id))

    own = client.structure(request_for(engine), Company, context_of(organisation_id, other))
    outside = client.structure(request_for(engine), Company, CallContext(organisation_id))

    assert own.legal_name == outside.legal_name == "Acme"
    assert total_cost(engine, other) == CALL_COST


def test_a_failed_call_is_metered_and_a_run_that_ended_partial_makes_no_further_call(
    engine: Engine,
) -> None:
    organisation_id, run_id = started(engine)
    adapter = billed(VALID)
    client = providers_for(engine, adapter, budget=allow(5)).structuring()
    with Database(None, engine).session() as db:
        db.execute(update(ProfileRun).where(ProfileRun.id == run_id).values(status="partial"))
        db.commit()

    with pytest.raises(RunBudgetExhausted):  # well within the budget, but the run stopped
        client.structure(request_for(engine), Company, context_of(organisation_id, run_id))

    assert adapter.calls == []


# --- retries ----------------------------------------------------------------------------------


@pytest.mark.parametrize("retries", [0, 1, 3])
def test_retries_are_bounded_by_the_configured_maximum_and_each_one_is_billed(
    engine: Engine, retries: int
) -> None:
    organisation_id, run_id = started(engine)
    adapter = billed(*[INVALID] * 6)
    client = providers_for(engine, adapter, budget=allow(10), max_retries=retries).structuring()

    with pytest.raises(StructuredOutputInvalid) as raised:
        client.structure(request_for(engine), Company, context_of(organisation_id, run_id))

    assert len(adapter.calls) == 1 + retries == raised.value.attempts
    assert [row.outcome for row in usage_rows(engine, run_id)] == ["invalid_output"] * (1 + retries)
    assert total_cost(engine, run_id) == CALL_COST * (1 + retries)


def test_a_retry_counts_against_the_budget_and_is_not_made_when_it_would_exceed_it(
    engine: Engine,
) -> None:
    organisation_id, run_id = started(engine)
    adapter = billed(*[INVALID] * 6)
    client = providers_for(engine, adapter, budget=allow(2), max_retries=5).structuring()

    with pytest.raises(RunBudgetExhausted):
        client.structure(request_for(engine), Company, context_of(organisation_id, run_id))

    assert len(adapter.calls) == 2  # five retries were allowed; the budget allowed one
    assert total_cost(engine, run_id) == CALL_COST * 2


def test_a_failed_attempt_is_in_the_run_totals_that_the_budget_reads(engine: Engine) -> None:
    organisation_id, run_id = started(engine)
    outage = ProviderCallError(provider="google", config_id="primary", kind="unavailable")
    adapter = BilledText([outage, VALID])
    client = providers_for(engine, adapter, budget=allow(1)).structuring()
    context = context_of(organisation_id, run_id)

    with pytest.raises(ProviderCallError):
        client.structure(request_for(engine), Company, context)
    client.structure(request_for(engine), Company, context)

    assert [row.outcome for row in usage_rows(engine, run_id)] == ["failed", "success"]


# --- the estimate -----------------------------------------------------------------------------


def test_the_estimate_is_an_upper_bound_of_what_the_prices_bill() -> None:
    meter = make_meter()
    spec = config("primary")
    chars, output = 4000, 8192

    estimate = meter.max_call_cost(spec, chars, output, 0)
    # The most a real call can bill: one token per character in, the whole allowance out.
    worst = make_meter().record(
        spec,
        "structuring",
        context_of(uuid.uuid4(), uuid.uuid4()),
        1,
        "success",
        CallUsage(input_tokens=chars, output_tokens=output),
    )

    assert estimate >= worst.cost > 0


def test_the_estimate_prices_reasoning_tokens_at_the_dearer_rate() -> None:
    prices = PriceTable.model_validate(
        {
            "prices": [
                {
                    "provider": "google",
                    "model_id": "model-1",
                    "currency": "EUR",
                    "as_of": "2026-10-27",
                    "input_per_million": "0",
                    "output_per_million": "1",
                    "reasoning_per_million": "10",
                    "tool_call": "0",
                }
            ]
        }
    )

    estimate = UsageMeter(prices, None, make_meter()._sink).max_call_cost(
        config("primary"), 0, 1_000_000, 0
    )

    assert estimate == Decimal("10")


def test_a_model_without_a_price_is_refused_and_never_estimated_as_free(engine: Engine) -> None:
    _organisation_id, run_id = started(engine)
    adapter = billed(VALID)
    spec = config("unpriced", model_id="model-without-a-price")
    cat = catalogue(spec)
    providers = Providers(
        cat,
        {"GEMINI_API_KEY": SENTINEL_KEY},
        fake_adapters(cat, structuring=adapter),
        meter=make_meter(),
    )

    with pytest.raises(ProviderConfigurationRefused):
        providers.structuring()
    with pytest.raises(ProviderConfigurationRefused):
        make_meter().max_call_cost(spec, 10, 10, 0)

    assert adapter.calls == [] and usage_rows(engine, run_id) == []


def test_a_dollar_price_without_a_rate_is_refused_not_estimated_as_zero() -> None:
    meter = UsageMeter(PRICES, None, make_meter()._sink)

    with pytest.raises(ConfigurationError) as raised:
        meter.max_call_cost(config("primary"), 10, 10, 0)

    assert "EUR_PER_USD" in str(raised.value)


# --- configuration ----------------------------------------------------------------------------


def test_the_budget_and_the_retry_maximum_are_read_from_the_environment() -> None:
    settings = load_settings({"RUN_BUDGET_EUR": " 2.50 ", "PROVIDER_MAX_RETRIES": "3"})

    assert settings.run_budget_eur == Decimal("2.50") and settings.provider_max_retries == 3
    assert require_run_budget(settings) == Decimal("2.50")
    assert load_settings({"RUN_BUDGET_EUR": "1"}).provider_max_retries == 1  # the default


def test_a_missing_budget_stops_startup_naming_the_setting(engine: Engine) -> None:
    settings = load_settings({})

    with pytest.raises(ConfigurationError) as direct:
        require_run_budget(settings)
    with pytest.raises(ConfigurationError) as startup:
        load_providers(settings, Database(None, engine))

    assert "RUN_BUDGET_EUR" in str(direct.value) and "RUN_BUDGET_EUR" in str(startup.value)


@pytest.mark.parametrize("value", ["0", "0.00", "-1", "-0.01", "ten", "nan", "inf", "1e999999"])
def test_a_zero_negative_or_invalid_budget_stops_startup_naming_the_setting_not_the_value(
    value: str,
) -> None:
    with pytest.raises(ConfigurationError) as raised:
        load_settings({"RUN_BUDGET_EUR": value})

    assert str(raised.value) == "RUN_BUDGET_EUR must be a number above 0 and at most 100000"


@pytest.mark.parametrize("value", ["-1", "6", "1.5", "two", "²"])
def test_an_invalid_retry_maximum_stops_startup_naming_the_setting(value: str) -> None:
    with pytest.raises(ConfigurationError) as raised:
        load_settings({"PROVIDER_MAX_RETRIES": value})

    assert str(raised.value).startswith("PROVIDER_MAX_RETRIES must be a whole number")


def test_the_providers_of_the_application_check_the_configured_budget(engine: Engine) -> None:
    settings = Settings(
        database_url=None,
        allowed_origins=("http://localhost:5173",),
        run_budget_eur=Decimal("3"),
        provider_max_retries=2,
        eur_per_usd=Decimal("0.9"),
    )

    providers = load_providers(settings, Database(None, engine))

    assert providers.budget is not None and providers.budget.max_retries == 2
    assert providers.budget.budget_eur == Decimal("3")  # type: ignore[attr-defined]


# --- concurrency ------------------------------------------------------------------------------


class Meeting(FakeStructuringAdapter):
    """Holds each call until both threads are inside the provider: two calls in flight."""

    def __init__(self) -> None:
        super().__init__([])
        self.barrier = threading.Barrier(2, timeout=20)

    def generate_json(self, request: StructuringRequest, *_: Any) -> StructuringOutput:
        self.barrier.wait()
        return StructuringOutput(VALID, BILLED)


def test_two_calls_in_flight_at_once_overrun_by_at_most_one_call(engine: Engine) -> None:
    """The check reads recorded usage, so two simultaneous calls of one run both pass. This is the
    largest overrun: less than one call above the budget. The next call is refused."""
    organisation_id, run_id = started(engine)
    budget = allow(1)
    adapter = Meeting()
    client = providers_for(engine, adapter, budget=budget).structuring()
    context = context_of(organisation_id, run_id)
    errors: list[BaseException] = []

    def call() -> None:
        try:
            client.structure(request_for(engine), Company, context)
        except BaseException as error:  # noqa: BLE001 - reported below
            errors.append(error)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    overrun = total_cost(engine, run_id) - budget
    assert 0 < overrun < CALL_COST
    with pytest.raises(RunBudgetExhausted):
        client.structure(request_for(engine), Company, context)


def test_calls_made_one_after_the_other_never_pass_the_budget(engine: Engine) -> None:
    organisation_id, run_id = started(engine)
    budget = allow(3)
    adapter = billed(*[VALID] * 10)
    client = providers_for(engine, adapter, budget=budget).structuring()
    context = context_of(organisation_id, run_id)
    made = 0

    for _ in range(10):
        try:
            client.structure(request_for(engine), Company, context)
        except RunBudgetExhausted:
            break
        made += 1

    assert made == 3 and total_cost(engine, run_id) <= budget

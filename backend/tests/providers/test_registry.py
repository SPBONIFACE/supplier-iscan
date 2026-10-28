"""Resolution of approved configurations, no fallback, key settings, and the structuring retry."""

from collections.abc import Mapping

import pytest

from app.providers.catalogue import ProviderConfigSpec
from app.providers.errors import (
    ProviderCallError,
    ProviderConfigurationRefused,
    ProviderSettingMissing,
    ProvidersNotReady,
    StructuredOutputInvalid,
)
from app.providers.fake import (
    FactoryLog,
    FakeRetrievalAdapter,
    FakeStructuringAdapter,
    fake_adapters,
)
from app.providers.interface import RetrievalRequest, RetrievedUrl, StructuringRequest
from app.providers.registry import Providers
from tests.providers.support import SENTINEL_KEY, Company, catalogue, config

GOOD = '{"legal_name": "Acme SA", "country": "FR"}'
REQUEST = StructuringRequest(instructions="Extract.", data="<data>Acme SA</data>")
ENV = {"GEMINI_API_KEY": SENTINEL_KEY, "ANTHROPIC_API_KEY": SENTINEL_KEY}


def make(
    *configs: ProviderConfigSpec,
    structuring: dict[str, FakeStructuringAdapter] | FakeStructuringAdapter | None = None,
    retrieval: dict[str, FakeRetrievalAdapter] | FakeRetrievalAdapter | None = None,
    environ: Mapping[str, str] = ENV,
    log: FactoryLog | None = None,
    roles: dict[str, str] | None = None,
) -> Providers:
    """Providers on `configs`; `roles` overrides the selected configuration per role, unchecked."""
    cat = catalogue(*configs)
    if roles:
        cat = cat.model_copy(update={"roles": cat.roles.model_copy(update=roles)})
    return Providers(cat, environ, fake_adapters(cat, structuring, retrieval, log))


def test_an_approved_configuration_is_used() -> None:
    fake = FakeStructuringAdapter([GOOD])
    client = make(config("primary"), structuring=fake).structuring()

    assert client.structure(REQUEST, Company) == Company(legal_name="Acme SA", country="FR")
    assert (client.config_id, client.provider, client.model_id) == ("primary", "google", "model-1")
    assert fake.calls == [REQUEST] and fake.schemas == ["Company"]


@pytest.mark.parametrize(
    ("primary", "reason"),
    [
        (config("primary", enabled=False), "disabled"),
        (config("primary", verified=False), "not been verified"),
        (config("primary", enabled=False, verified=False), "disabled"),
        (config("primary", "mistral", "conversations"), "does not support the structuring role"),
    ],
)
def test_a_refused_configuration_is_never_called_and_nothing_else_is_tried(
    primary: ProviderConfigSpec, reason: str
) -> None:
    log = FactoryLog()
    fakes = {"primary": FakeStructuringAdapter([GOOD]), "other": FakeStructuringAdapter([GOOD])}
    providers = make(
        config("other", "anthropic", "messages"),
        primary,
        structuring=fakes,
        log=log,
        roles={"structuring": "primary"},
    )

    with pytest.raises(ProviderConfigurationRefused) as raised:
        providers.structuring()

    assert reason in str(raised.value)
    assert raised.value.config_id == "primary"
    assert log.built == []  # no adapter built, so no network call is possible
    assert fakes["primary"].calls == [] and fakes["other"].calls == []


def test_an_unknown_configuration_is_refused() -> None:
    log = FactoryLog()
    providers = make(config("primary"), structuring=FakeStructuringAdapter([GOOD]), log=log)

    with pytest.raises(ProviderConfigurationRefused, match="not in the approved list"):
        providers.structuring("someone-elses-config")
    assert log.built == []


def test_when_the_primary_fails_no_other_adapter_is_called() -> None:
    failing = FakeStructuringAdapter([TimeoutError("slow")])
    spare = FakeStructuringAdapter([GOOD])
    log = FactoryLog()
    providers = make(
        config("primary"),
        config("spare", "anthropic", "messages"),
        structuring={"primary": failing, "spare": spare},
        log=log,
    )

    with pytest.raises(ProviderCallError) as raised:
        providers.structuring().structure(REQUEST, Company)

    assert raised.value.kind == "timeout" and raised.value.retryable
    assert log.built == ["primary"]
    assert len(failing.calls) == 1 and spare.calls == []


def test_a_schema_failure_is_retried_once_then_raised_as_a_typed_error() -> None:
    fake = FakeStructuringAdapter(['{"legal_name": "Acme SA"}', "not json at all"])

    with pytest.raises(StructuredOutputInvalid) as raised:
        make(config("primary"), structuring=fake).structuring().structure(REQUEST, Company)

    assert len(fake.calls) == 2
    assert (raised.value.schema_name, raised.value.attempts) == ("Company", 2)
    assert raised.value.retryable


def test_free_text_around_json_is_not_parsed() -> None:
    fake = FakeStructuringAdapter([f"Here you go: {GOOD}", f"```json\n{GOOD}\n```"])

    with pytest.raises(StructuredOutputInvalid):
        make(config("primary"), structuring=fake).structuring().structure(REQUEST, Company)


def test_retrieval_uses_the_configured_retrieval_configuration() -> None:
    urls = [RetrievedUrl(url="https://a.example/1"), RetrievedUrl(url="https://a.example/1")]
    fake = FakeRetrievalAdapter([urls])
    providers = make(
        config("structurer"),
        config("searcher", "perplexity", "chat_completions"),
        retrieval={"searcher": fake},
        environ={**ENV, "PERPLEXITY_API_KEY": SENTINEL_KEY},
        roles={"retrieval": "searcher"},
    )

    result = providers.retrieval().retrieve(RetrievalRequest(instructions="i", query="q"))

    assert [item.url for item in result.urls] == ["https://a.example/1"]
    assert providers.selected("retrieval") == "searcher"
    assert providers.selected("structuring") == "structurer"


def test_a_missing_key_is_refused_before_any_call_naming_the_setting() -> None:
    log = FactoryLog()
    providers = make(
        config("primary"), structuring=FakeStructuringAdapter([GOOD]), environ={}, log=log
    )

    with pytest.raises(ProviderSettingMissing) as raised:
        providers.structuring()

    assert raised.value.setting == "GEMINI_API_KEY"
    assert "GEMINI_API_KEY" in str(raised.value)
    assert log.built == []  # the key is checked before the adapter is built


def test_run_start_reports_missing_settings_by_name() -> None:
    configs = (config("structurer"), config("searcher", "perplexity", "chat_completions"))
    roles = {"retrieval": "searcher"}
    providers = make(*configs, environ={"GEMINI_API_KEY": "  "}, roles=roles)

    assert providers.missing_settings() == ["GEMINI_API_KEY", "PERPLEXITY_API_KEY"]
    with pytest.raises(ProvidersNotReady) as raised:
        providers.check_ready()
    assert raised.value.missing_settings == ["GEMINI_API_KEY", "PERPLEXITY_API_KEY"]

    environ = {"GEMINI_API_KEY": SENTINEL_KEY, "PERPLEXITY_API_KEY": SENTINEL_KEY}
    ready = make(*configs, environ=environ, roles=roles)
    ready.check_ready()
    assert ready.missing_settings() == []


def test_run_start_reports_an_unapproved_selected_configuration() -> None:
    with pytest.raises(ProvidersNotReady, match="not been verified"):
        make(config("primary", verified=False)).check_ready()


def test_errors_never_contain_the_key() -> None:
    fake = FakeStructuringAdapter([RuntimeError(f"bad key {SENTINEL_KEY}")])
    with pytest.raises(ProviderCallError) as raised:
        make(config("primary"), structuring=fake).structuring().structure(REQUEST, Company)
    errors = [
        raised.value,
        ProviderCallError(provider="google", config_id="c", kind="authentication", status_code=401),
        ProviderSettingMissing(provider="google", config_id="c", setting="GEMINI_API_KEY"),
    ]

    for error in errors:
        assert SENTINEL_KEY not in str(error) and SENTINEL_KEY not in repr(error.args)
    assert raised.value.__context__ is None and raised.value.__cause__ is None

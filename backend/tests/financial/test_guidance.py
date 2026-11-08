"""The financial evidence guidance (#26): the country table, the access statuses, the message.
Pure functions and files: no database, no provider, no network."""

import ast
import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from app.config import ConfigurationError, Settings
from app.content import CONTENT_DIR, load_schema
from app.financial.guidance import (
    DOCUMENTS_TO_REQUEST,
    STATUSES,
    Observations,
    access_status,
    build_guidance,
    financial_year,
)
from app.financial.table import EXAMPLE_FILE, load_country_table
from app.main import create_app, load_countries
from tests.support import LOCAL_ORIGIN

SCHEMA = "country-table.schema.json"
TABLE = load_country_table()
APP = Path(__file__).resolve().parents[2] / "app"


def example() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))
    return document


def write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "countries.json"
    path.write_text(document if isinstance(document, str) else json.dumps(document))
    return path


def guidance(country: str | None = "XX", language: str = "en", **observations: Any) -> Any:
    found = build_guidance(
        TABLE,
        country,
        language,
        2025,
        natural_person=False,
        observations=Observations(**observations),
    )
    assert found is not None
    return found


# --- schema, example and loading -------------------------------------------------------------


def test_the_schema_is_published_and_the_example_validates_and_is_marked_as_an_example() -> None:
    assert (CONTENT_DIR / SCHEMA).is_file()
    Draft202012Validator.check_schema(load_schema(SCHEMA))
    Draft202012Validator(load_schema(SCHEMA)).validate(example())

    assert TABLE.example is True and "example" in example()["$comment"].lower()
    assert set(TABLE.countries) == {"XX"}
    row = TABLE.countries["XX"]
    assert row.registry_name and row.registry_url.startswith("https://") and row.last_checked


def test_a_configured_table_replaces_the_example(tmp_path: Path) -> None:
    document = copy.deepcopy(example())
    document["example"] = False
    document["countries"] = [document["countries"][0]]
    document["countries"][0]["country"] = "DE"

    table = load_country_table(write(tmp_path, document))

    assert set(table.countries) == {"DE"} and table.example is False
    assert table.content_hash != TABLE.content_hash


@pytest.mark.parametrize(
    ("change", "failing_path"),
    [
        (lambda d: d.pop("countries"), "(document)"),
        (lambda d: d["countries"][0].update(last_checked="yesterday"), "countries/0/last_checked"),
        (lambda d: d["countries"][0].update(country="gb"), "countries/0/country"),
        (lambda d: d["countries"][0].update(registry_url="http://x"), "countries/0/registry_url"),
        (
            lambda d: d["countries"][0]["documents"][0].update(access="no_filing_identified"),
            "countries/0/documents/0/access",
        ),
        (
            lambda d: d["countries"][0]["documents"][0].update(access="registry_unavailable"),
            "countries/0/documents/0/access",
        ),
    ],
)
def test_an_invalid_table_is_refused_with_the_file_and_the_failing_path(
    tmp_path: Path, change: Any, failing_path: str
) -> None:
    document = copy.deepcopy(example())
    change(document)
    path = write(tmp_path, document)

    with pytest.raises(ConfigurationError) as error:
        load_country_table(path)

    assert str(path) in str(error.value) and failing_path in str(error.value)


def test_a_duplicate_country_and_a_missing_document_type_are_refused(tmp_path: Path) -> None:
    duplicate = copy.deepcopy(example())
    duplicate["countries"].append(copy.deepcopy(duplicate["countries"][0]))
    with pytest.raises(ConfigurationError, match="duplicate country 'XX'"):
        load_country_table(write(tmp_path, duplicate))

    repeated = copy.deepcopy(example())
    repeated["countries"][0]["documents"][1]["type"] = "income_statement"
    with pytest.raises(ConfigurationError, match="countries/0/documents"):
        load_country_table(write(tmp_path, repeated))


def test_an_unreadable_table_and_invalid_json_name_the_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="cannot be read"):
        load_country_table(tmp_path / "missing.json")
    with pytest.raises(ConfigurationError, match="not valid JSON"):
        load_country_table(write(tmp_path, "{not json"))


def test_an_invalid_table_stops_startup_naming_the_file(tmp_path: Path) -> None:
    document = copy.deepcopy(example())
    document["countries"][0]["last_checked"] = "soon"
    path = write(tmp_path, document)
    settings = Settings(
        database_url=None,
        allowed_origins=(LOCAL_ORIGIN,),
        country_table_file=str(path),
        run_budget_eur=Decimal(5),
    )

    with pytest.raises(ConfigurationError, match="countries/0/last_checked") as error:
        load_countries(settings)
    assert str(path) in str(error.value)
    with pytest.raises(ConfigurationError):
        create_app(settings)


# --- access statuses -------------------------------------------------------------------------


def test_a_failed_registry_request_is_registry_unavailable_never_no_filing_identified() -> None:
    assert access_status("public_download", "request_failed") == "registry_unavailable"
    assert access_status("reduced_disclosure", "request_failed") == "registry_unavailable"
    assert access_status("public_download", "no_filing") == "no_filing_identified"
    assert access_status("paid", "found") == "paid" and access_status("paid", None) == "paid"

    failed = guidance(outcomes={"income_statement": "request_failed", "notes": "request_failed"})
    by_type = {item.type: item.access for item in failed.documents}
    assert by_type["income_statement"] == "registry_unavailable"
    assert by_type["notes"] == "registry_unavailable"
    assert "no_filing_identified" not in by_type.values()
    assert "does not show that no filing exists" in failed.message


def test_every_document_has_exactly_one_status_of_the_list() -> None:
    for country in ("XX",):
        found = guidance(country)
        assert [item.type for item in found.documents] == [
            "income_statement",
            "balance_sheet",
            "notes",
            "audit_report",
        ]
        assert all(item.access in STATUSES for item in found.documents)


@pytest.mark.parametrize("language", ["en", "fr"])
def test_paid_reduced_and_unreachable_documents_are_never_called_unavailable(
    language: str,
) -> None:
    found = guidance(
        "XX",
        language,
        outcomes={"income_statement": "request_failed", "balance_sheet": "no_filing"},
    )
    statuses = {item.access for item in found.documents}
    assert {"paid", "registry_unavailable", "no_filing_identified"} <= statuses
    reduced = guidance("XX", language)
    assert "reduced_disclosure" in {item.access for item in reduced.documents}

    for text in (found.message.casefold(), reduced.message.casefold()):
        for word in ("unavailable", "not available", "indisponible", "non disponible"):
            assert word not in text


def test_where_access_is_paid_the_message_links_to_the_registry_and_buys_nothing() -> None:
    found = guidance("XX")
    paid = [item for item in found.documents if item.access == "paid"]

    assert paid and all(item.registry_link == "https://registry.example/" for item in paid)
    assert "https://registry.example/" in found.message
    assert "buys no document" in found.message
    assert "No credit score, estimate or commercial report" in found.message


def test_the_guidance_code_makes_no_network_call_no_provider_call_and_no_purchase() -> None:
    forbidden = (
        "app.providers",
        "app.http_client",
        "app.registries",
        "httpx",
        "requests",
        "urllib",
    )
    for path in (APP / "financial").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert not name.startswith(forbidden), f"{path.name} imports {name}"


# --- entity, period, message -----------------------------------------------------------------


def test_the_suppliers_own_accounts_are_kept_apart_from_group_accounts() -> None:
    found = guidance(
        "XX",
        group_accounts_only=True,
        outcomes={"balance_sheet": "found"},
        latest_period=2023,
    )

    scopes = [(item.type, item.scope) for item in found.documents]
    assert ("balance_sheet", "supplier_entity") in scopes and ("balance_sheet", "group") in scopes
    assert [scope for _type, scope in scopes].count("group") == 1
    assert "supplier_entity_accounts" in found.missing_evidence
    assert "more_recent_period" in found.missing_evidence
    assert "group accounts" in found.message


def test_the_message_names_the_missing_evidence_and_the_documents_to_request() -> None:
    found = guidance("XX")

    assert found.missing_evidence == ("income_statement", "full_notes", "audit_report")
    assert found.documents_to_request == DOCUMENTS_TO_REQUEST
    for wording in (
        "income statement",
        "full notes",
        "audit report",
        "statutory accounts",
        "audited statements",
        "tax schedules",
        "management accounts",
    ):
        assert wording in found.message
    assert "financial year 2025" in found.message
    assert "last checked 2000-01-01" in found.message and "example table" in found.message
    assert found.gap_evidence.startswith("income statement")
    # Evidence wording: absence is "No public evidence found", never a claim about the supplier.
    assert "No public evidence found" in found.message
    for negative in ("does not have", "has no ", "is not audited", "hides"):
        assert negative not in found.message


@pytest.mark.parametrize("language", ["en", "fr"])
def test_a_collected_financial_fact_removes_the_absence_phrase_and_its_document_from_the_gaps(
    language: str,
) -> None:
    none_kept = guidance("XX", language)
    some = guidance("XX", language, collected=frozenset({"income_statement"}))

    phrase = "No public evidence found" if language == "en" else "Aucune preuve publique trouvée"
    assert phrase in none_kept.message and phrase not in some.message
    assert some.missing_evidence == ("full_notes", "audit_report")
    assert "income_statement" not in some.missing_evidence
    still = "Evidence still missing: " if language == "en" else "Éléments encore manquants : "
    assert still in some.message
    # What to request is still named, and the gap text names only what is missing.
    assert ("statutory accounts" if language == "en" else "comptes annuels") in some.message
    assert some.gap_evidence.startswith("full notes" if language == "en" else "annexe")
    assert "income statement" not in some.gap_evidence


def test_a_balance_sheet_fact_alone_also_removes_the_absence_phrase() -> None:
    some = guidance("XX", collected=frozenset({"balance_sheet"}))

    assert "No public evidence found" not in some.message
    assert some.missing_evidence == ("income_statement", "full_notes", "audit_report")


def test_a_country_missing_from_the_table_still_names_the_documents_to_request() -> None:
    found = guidance("ZZ")

    assert found.configured is False and found.documents == ()
    assert found.registry_name is None and found.registry_url is None
    assert "No registry guidance is configured for this country" in found.message
    assert "statutory accounts" in found.message and "management accounts" in found.message
    no_country = guidance(None, "fr")
    assert "Aucune indication de registre n'est configurée" in no_country.message
    assert "comptes annuels" in no_country.message


def test_a_natural_person_business_gets_no_financial_guidance() -> None:
    assert build_guidance(TABLE, "XX", "en", 2025, natural_person=True) is None


def test_nothing_is_missing_when_everything_is_collected() -> None:
    collected = frozenset({"income_statement", "notes", "audit_report"})
    assert build_guidance(TABLE, "XX", "en", 2025, False, Observations(collected=collected)) is None


def test_the_guidance_is_the_documented_json_and_the_year_is_the_last_one_over() -> None:
    from datetime import date

    assert financial_year(date(2026, 11, 5)) == 2025
    payload = guidance("XX").to_json()
    assert set(payload) == {
        "country",
        "financial_year",
        "configured",
        "example_table",
        "registry_name",
        "registry_url",
        "last_checked",
        "documents",
        "missing_evidence",
        "documents_to_request",
        "message",
    }
    assert json.dumps(payload)

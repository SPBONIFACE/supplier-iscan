"""The public demo (#50): the command that builds it, the read-only endpoints, isolation and the
refusal of every write."""

import os
import re
import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, insert, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.config import ConfigurationError, Settings, load_settings
from app.demo.__main__ import main as demo_command
from app.demo.build import DemoOrganisationRefused, load_demo_profiles
from app.demo.readonly import READ_ONLY
from app.models import DemoProfile, Job, LlmUsage, ProfileRun, UsageEvent
from app.pdf.disclaimer import disclaimer_text
from app.profile_definition import load_profile_definition
from tests.auth_support import send_with_session
from tests.contract.test_auth_contract import assert_matches_contract
from tests.demo.support import (
    AUTHOR,
    PERSON,
    SECRET_PATHS,
    build,
    build_rows,
    client_with_recording_provider,
    finished_run,
    items_of,
    stored_json,
)
from tests.factories import create_organisation, create_session, create_user
from tests.runs_support import create_run
from tests.support import make_client

WRITES = ("POST", "PUT", "PATCH", "DELETE")


def two_profiles(engine: Engine, settings: Settings) -> tuple[Any, list[DemoProfile]]:
    """A demo organisation with two finished runs, copied; and the demo profiles."""
    demo = finished_run(engine, settings)
    # A second finished run of the same organisation, with the same kind of content.
    from tests.assessment.test_stage import add_fact

    run_id = create_run(
        engine, demo.organisation_id, "Beta Works", status="completed", enqueue=False
    )
    add_fact(engine, demo.organisation_id, run_id, "quality_management", "ISO 14001")
    return demo, build(engine, demo)


# --- the command -------------------------------------------------------------------------------


def test_the_command_copies_finished_runs_with_names_stripped(
    engine: Engine, settings: Settings
) -> None:
    demo = finished_run(engine, settings)
    run = demo.run_id

    profiles = build(engine, demo)

    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.demo is True and profile.supplier_name == "Acme Supplies SA"
    fields = {fact["field"] for fact in profile.facts}
    assert "quality_management" in fields and "management_team" not in fields  # people dropped
    everything = stored_json(engine)
    assert PERSON not in everything and AUTHOR not in everything
    assert 'reviewed_by": "' not in everything
    # No real id is copied: the run, the organisation, the facts and the sources.
    for real in (run, demo.organisation_id, *demo.fact_ids.values()):
        assert str(real) not in everything
    assert profile.id != run
    # Statements that cite a dropped fact are dropped; the others keep provenance and status.
    texts = [item["text"] for item in profile.assessment["items"]]
    assert texts and not any(PERSON in value for value in texts)
    assert {item["provenance"]["status"] for item in profile.assessment["items"]} == {"ai_draft"}
    new_fact_ids = {fact["id"] for fact in profile.facts}
    for item in profile.assessment["items"]:
        assert set(item["cited_fact_ids"]) <= new_fact_ids
    assert len(items_of(engine, run)) >= 3  # the original run is untouched


def test_running_the_command_again_replaces_the_set(engine: Engine, settings: Settings) -> None:
    demo = finished_run(engine, settings)
    first = build(engine, demo)[0].id

    second = build(engine, demo)

    assert len(second) == 1 and second[0].id != first
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(DemoProfile)) == 1


def test_only_finished_runs_with_a_profile_are_copied(engine: Engine, settings: Settings) -> None:
    demo = finished_run(engine, settings)
    for status in ("queued", "running", "stopped", "failed", "insufficient_sources", "paused"):
        create_run(engine, demo.organisation_id, status.title(), status=status, enqueue=False)

    assert [profile.supplier_name for profile in build(engine, demo)] == ["Acme Supplies SA"]


def test_a_natural_person_business_is_not_copied(engine: Engine, settings: Settings) -> None:
    demo = finished_run(engine, settings, natural_person=True)

    assert build(engine, demo) == []


def test_the_command_refuses_any_other_organisation(engine: Engine, settings: Settings) -> None:
    demo = finished_run(engine, settings)
    build(engine, demo)
    customer = create_organisation(engine, name="A customer")
    create_run(engine, customer, "Customer Supplier", status="completed", enqueue=False)

    with Session(engine) as db, pytest.raises(DemoOrganisationRefused):
        load_demo_profiles(db, demo.settings, load_profile_definition(), customer)

    assert [row.supplier_name for row in build_rows(engine)] == ["Acme Supplies SA"]


def test_the_command_refuses_when_no_demo_organisation_is_configured(
    engine: Engine, settings: Settings
) -> None:
    demo = finished_run(engine, settings)

    with Session(engine) as db, pytest.raises(DemoOrganisationRefused, match="not set"):
        load_demo_profiles(db, settings, load_profile_definition(), demo.organisation_id)
    assert build_rows(engine) == []


def test_the_command_line_replaces_the_set_and_refuses_another_organisation(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    demo = finished_run(engine, settings)
    assert settings.database_url
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("DEMO_ORGANISATION_ID", str(demo.organisation_id))

    assert demo_command(["load", "--organisation", str(demo.organisation_id)]) == 0
    assert "1 profile(s)" in capsys.readouterr().out
    assert demo_command(["load", "--organisation", str(uuid.uuid4())]) == 1
    assert "not the configured demo organisation" in capsys.readouterr().err
    assert len(build_rows(engine)) == 1
    monkeypatch.delenv("DEMO_ORGANISATION_ID")
    assert demo_command(["load", "--organisation", str(demo.organisation_id)]) == 1


def test_the_demo_organisation_setting_is_validated() -> None:
    assert load_settings({"DEMO_ORGANISATION_ID": ""}).demo_organisation_id is None
    value = uuid.uuid4()
    assert load_settings({"DEMO_ORGANISATION_ID": str(value)}).demo_organisation_id == value
    with pytest.raises(ConfigurationError, match="DEMO_ORGANISATION_ID"):
        load_settings({"DEMO_ORGANISATION_ID": "not-an-id"})


# --- browsing without an account ---------------------------------------------------------------


def test_the_list_and_the_card_need_no_account(engine: Engine, settings: Settings) -> None:
    demo, profiles = two_profiles(engine, settings)
    client = make_client(settings=demo.settings, engine=engine)  # no cookie, no provider key

    listing = client.get("/demo/profiles")
    detail = client.get(f"/demo/profiles/{profiles[0].id}")

    assert listing.status_code == 200 and detail.status_code == 200
    assert_matches_contract(listing, "/demo/profiles", "get")
    assert_matches_contract(detail, "/demo/profiles/{id}", "get")
    body = detail.json()
    assert [item["id"] for item in listing.json()["items"]] == [str(p.id) for p in profiles]
    assert body["run"]["id"] == str(profiles[0].id)
    assert body["run"]["supplier_name"] == "Acme Supplies SA"
    assert body["facts"] and body["sources"] == []
    statuses = {item["provenance"]["status"] for item in body["assessment"]["items"]}
    assert statuses == {"ai_draft"}  # shown as "AI draft, pending your validation"
    assert listing.json()["disclaimer"] == disclaimer_text(demo.settings, "en")
    assert body["disclaimer"] and detail.json()["disclaimer"] == listing.json()["disclaimer"]
    french = client.get(f"/demo/profiles/{profiles[0].id}?lang=fr").json()["disclaimer"]
    assert french == disclaimer_text(demo.settings, "fr")


def test_the_comparison_of_two_or_more_demo_profiles(engine: Engine, settings: Settings) -> None:
    demo, profiles = two_profiles(engine, settings)
    client = make_client(settings=demo.settings, engine=engine)
    first, second = profiles[0].id, profiles[1].id

    ok = client.get("/demo/comparison", params={"profile_ids": [str(second), str(first)]})

    assert ok.status_code == 200
    assert_matches_contract(ok, "/demo/comparison", "get")
    assert [item["run"]["id"] for item in ok.json()["items"]] == [str(second), str(first)]
    assert ok.json()["disclaimer"]
    one = client.get("/demo/comparison", params={"profile_ids": [str(first), str(first)]})
    assert one.status_code == 422
    assert_matches_contract(one, "/demo/comparison", "get")
    many = [str(uuid.uuid4()) for _ in range(demo.settings.comparison_max_profiles + 1)]
    assert client.get("/demo/comparison", params={"profile_ids": many}).status_code == 422
    unknown = client.get(
        "/demo/comparison", params={"profile_ids": [str(first), str(uuid.uuid4())]}
    )
    assert unknown.status_code == 404
    assert_matches_contract(unknown, "/demo/comparison", "get")
    assert client.get("/demo/comparison").status_code == 422


def test_the_profile_definition_is_public(engine: Engine, settings: Settings) -> None:
    client = make_client(settings=settings, engine=engine)

    response = client.get("/demo/profile-definition", params={"language": "fr"})

    assert response.status_code == 200 and response.json()["language"] == "fr"
    assert_matches_contract(response, "/demo/profile-definition", "get")
    assert client.get("/demo/profile-definition?language=xx").status_code == 422


def test_the_card_pdf_carries_the_disclaimer(engine: Engine, settings: Settings) -> None:
    demo, profiles = two_profiles(engine, settings)
    client = make_client(settings=demo.settings, engine=engine)

    response = client.get(f"/demo/profiles/{profiles[0].id}/pdf")

    if response.status_code == 503:
        if os.environ.get("CI"):
            pytest.fail("WeasyPrint's system libraries (Pango) must be installed in CI")
        pytest.skip("WeasyPrint's system libraries (Pango) are not installed here")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert "supplier-card-acme-supplies-sa" in response.headers["content-disposition"]


def test_the_card_pdf_html_has_the_disclaimer_and_no_name(
    engine: Engine, settings: Settings
) -> None:
    # The HTML the PDF is made from, which needs no system library (the PDF test above skips
    # where Pango is missing).
    import html as htmllib

    from app.db import utc_now
    from app.demo.routes import card_input
    from app.pdf.render import render_html

    demo, profiles = two_profiles(engine, settings)
    definition = load_profile_definition()
    for lang in ("en", "fr"):
        card = card_input(profiles[0], demo.settings, definition, lang, utc_now())

        html = htmllib.unescape(render_html(card))

        assert disclaimer_text(demo.settings, lang) in html
        assert "Acme Supplies SA" in html
        for hidden in (PERSON, AUTHOR, str(demo.run_id), str(demo.organisation_id)):
            assert hidden not in html


def test_the_pdf_of_an_unknown_or_real_run_is_a_404(engine: Engine, settings: Settings) -> None:
    demo, _ = two_profiles(engine, settings)
    client = make_client(settings=demo.settings, engine=engine)

    for raw in (str(demo.run_id), str(uuid.uuid4()), "not-a-uuid"):
        assert client.get(f"/demo/profiles/{raw}/pdf").status_code == 404


def test_with_no_demo_profile_the_demo_is_empty_not_an_error(
    engine: Engine, settings: Settings
) -> None:
    client = make_client(settings=settings, engine=engine)

    response = client.get("/demo/profiles")

    assert response.status_code == 200 and response.json()["items"] == []
    assert response.json()["disclaimer"]
    assert_matches_contract(response, "/demo/profiles", "get")
    assert client.get("/demo/comparison", params={"profile_ids": ["a", "b"]}).status_code == 404


# --- isolation --------------------------------------------------------------------------------


def test_a_real_run_id_is_a_404_on_every_demo_route(engine: Engine, settings: Settings) -> None:
    demo, profiles = two_profiles(engine, settings)
    other = create_organisation(engine, name="A customer")
    customer_run = create_run(engine, other, "Customer Supplier", status="completed", enqueue=False)
    client = make_client(settings=demo.settings, engine=engine)

    for real in (demo.run_id, customer_run, demo.organisation_id):
        detail = client.get(f"/demo/profiles/{real}")
        assert detail.status_code == 404
        assert_matches_contract(detail, "/demo/profiles/{id}", "get")
        mixed = client.get(
            "/demo/comparison", params={"profile_ids": [str(profiles[0].id), str(real)]}
        )
        assert mixed.status_code == 404 and "Acme" not in mixed.text


def test_demo_responses_hold_no_user_organisation_or_usage_data(
    engine: Engine, settings: Settings
) -> None:
    demo, profiles = two_profiles(engine, settings)
    member = create_user(engine, organisation_id=demo.organisation_id)
    client = make_client(settings=demo.settings, engine=engine)
    responses = [
        client.get("/demo/profiles"),
        client.get(f"/demo/profiles/{profiles[0].id}"),
        client.get("/demo/comparison", params={"profile_ids": [str(p.id) for p in profiles]}),
    ]

    for response in responses:
        assert response.status_code == 200
        text_ = response.text
        for key in SECRET_PATHS:
            assert f'"{key}"' not in text_, key
        for real in (demo.run_id, demo.organisation_id, member.id, member.email, PERSON, AUTHOR):
            assert str(real) not in text_


def test_the_demo_routes_read_only_the_demo_table(engine: Engine, settings: Settings) -> None:
    demo, profiles = two_profiles(engine, settings)
    client = make_client(settings=demo.settings, engine=engine)
    statements: list[str] = []

    def record(connection: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        client.get("/demo/profiles")
        client.get(f"/demo/profiles/{profiles[0].id}")
        client.get("/demo/comparison", params={"profile_ids": [str(p.id) for p in profiles]})
        client.get("/demo/profile-definition")
    finally:
        event.remove(engine, "before_cursor_execute", record)

    tables = {
        name
        for statement in statements
        for name in re.findall(r"(?:FROM|JOIN|INTO|UPDATE)\s+\"?(\w+)", statement, re.IGNORECASE)
    }
    assert statements and tables == {"demo_profiles"}
    assert not any(re.match(r"\s*(INSERT|UPDATE|DELETE)", s, re.IGNORECASE) for s in statements)


def test_the_demo_session_is_a_read_only_transaction(engine: Engine, settings: Settings) -> None:
    from starlette.requests import Request

    from app.demo.routes import demo_session

    client = make_client(settings=settings, engine=engine)
    request = Request({"type": "http", "app": client.app, "headers": [], "method": "GET"})
    generator = demo_session(request)
    session = next(generator)
    with pytest.raises(DBAPIError, match="read-only"):
        session.execute(
            insert(DemoProfile).values(
                position=1, supplier_name="x", run={}, facts=[], assessment={}, sources=[]
            )
        )
    session.rollback()
    session.close()


# --- nothing can write, call a model, queue or crawl -------------------------------------------


def snapshot(engine: Engine) -> dict[str, int]:
    with Session(engine) as db:
        return {
            model.__tablename__: db.scalar(select(func.count()).select_from(model)) or 0
            for model in (DemoProfile, Job, LlmUsage, ProfileRun, UsageEvent)
        }


def demo_routes(profile_id: uuid.UUID, other_id: uuid.UUID) -> list[str]:
    return [
        "/demo",
        "/demo/profiles",
        f"/demo/profiles/{profile_id}",
        f"/demo/profiles/{profile_id}/pdf",
        f"/demo/profiles/{profile_id}/rerun",
        f"/demo/profiles/{profile_id}/review",
        f"/demo/profiles/{profile_id}/criteria",
        f"/demo/profiles/{profile_id}/buyer-inputs/notes",
        "/demo/comparison",
        "/demo/comparison/pdf",
        "/demo/profile-definition",
        "/demo/runs",
        "/demo/anything/else",
        f"/demo/profiles/{other_id}",
    ]


def test_every_write_to_every_demo_route_is_refused_with_403(
    engine: Engine, settings: Settings
) -> None:
    demo, profiles = two_profiles(engine, settings)
    recording = client_with_recording_provider(engine, demo.settings)
    member = create_user(engine, organisation_id=demo.organisation_id)
    token = create_session(engine, member.id)
    before = snapshot(engine)

    for path in demo_routes(profiles[0].id, demo.run_id):
        for method in (*WRITES, "HEAD", "OPTIONS"):
            for session in (None, token):  # a visitor, and a signed-in member
                if session is None:
                    response = recording.client.request(method, path, json={"x": 1})
                else:
                    response = send_with_session(
                        recording.client, method, path, session, json={"x": 1}
                    )
                assert response.status_code == 403, (method, path, response.status_code)
                if method != "HEAD":
                    assert response.json() == {"detail": READ_ONLY}

    assert recording.adapter.calls == []  # not one LLM call
    assert snapshot(engine) == before  # nothing written, no job queued


def test_every_demo_route_makes_no_llm_call_and_queues_no_job(
    engine: Engine, settings: Settings
) -> None:
    demo, profiles = two_profiles(engine, settings)
    recording = client_with_recording_provider(engine, demo.settings)
    before = snapshot(engine)
    ids = [str(p.id) for p in profiles]

    statuses = [
        recording.client.get("/demo/profiles").status_code,
        recording.client.get(f"/demo/profiles/{profiles[0].id}").status_code,
        recording.client.get(f"/demo/profiles/{profiles[0].id}/pdf").status_code,
        recording.client.get("/demo/comparison", params={"profile_ids": ids}).status_code,
        recording.client.get("/demo/profile-definition").status_code,
    ]

    assert statuses[:2] == [200, 200] and statuses[3:] == [200, 200]
    assert statuses[2] in (200, 503)  # 503 only where Pango is missing
    assert recording.adapter.calls == []
    assert snapshot(engine) == before


def test_the_demo_works_without_a_provider_key_and_with_every_provider_failing(
    engine: Engine, settings: Settings
) -> None:
    from app.providers.errors import ProviderCallError
    from app.providers.fake import FakeStructuringAdapter
    from tests.extraction.support import providers_with

    demo, profiles = two_profiles(engine, settings)
    # No key at all: the default test providers hold none (GET /health would list them missing).
    keyless = make_client(settings=demo.settings, engine=engine)
    assert keyless.get("/health").json()["missing_settings"]
    assert keyless.get(f"/demo/profiles/{profiles[0].id}").status_code == 200
    # Every provider unreachable: any call fails.
    failing = FakeStructuringAdapter(
        [ProviderCallError(provider="p", config_id="c", kind="timeout")] * 20
    )
    from app.main import create_app

    app = create_app(demo.settings, engine=engine, providers=providers_with(failing))
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    assert client.get("/demo/profiles").status_code == 200
    assert client.get(f"/demo/profiles/{profiles[0].id}").status_code == 200
    assert failing.calls == []


def test_a_visitor_on_a_member_route_gets_401_and_a_member_keeps_the_session(
    engine: Engine, settings: Settings
) -> None:
    demo, profiles = two_profiles(engine, settings)
    client = make_client(settings=demo.settings, engine=engine)
    member = create_user(engine, organisation_id=demo.organisation_id)
    token = create_session(engine, member.id)

    for method, path in (
        ("GET", "/runs"),
        ("GET", f"/runs/{demo.run_id}"),
        ("POST", "/runs"),
        ("GET", "/comparison"),
        ("GET", "/organisation"),
    ):
        assert client.request(method, path).status_code == 401, path

    assert (
        send_with_session(client, "GET", f"/demo/profiles/{profiles[0].id}", token).status_code
        == 200
    )
    assert send_with_session(client, "GET", "/auth/me", token).status_code == 200  # still signed in
    assert send_with_session(client, "GET", "/runs", token).status_code == 200


def test_the_spend_cap_does_not_touch_the_demo(engine: Engine, settings: Settings) -> None:
    from dataclasses import replace

    demo, profiles = two_profiles(engine, settings)
    client = make_client(
        settings=replace(demo.settings, monthly_spend_cap_eur=Decimal("0.01")), engine=engine
    )

    assert client.get("/demo/profiles").status_code == 200

"""GET /runs/{id}/pdf (#39): access, status codes, language, file name, content."""

import io
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AssessmentItem, ProfileRun
from app.pdf.routes import safe_filename
from tests.auth_support import send_with_session
from tests.contract.test_auth_contract import assert_matches_contract
from tests.factories import create_organisation, create_session, create_user
from tests.pdf.db_support import add_fact, finished_run
from tests.pdf.support import flat_text_of, metadata_of
from tests.runs_support import create_identity, create_run
from tests.support import LOCAL_ORIGIN, make_client


def add_statement(
    engine: Engine,
    organisation_id: uuid.UUID,
    run_id: uuid.UUID,
    text: str,
    status: str = "ai_draft",
    position: int = 0,
) -> None:
    with Session(engine) as db:
        db.add(
            AssessmentItem(
                organisation_id=organisation_id,
                run_id=run_id,
                position=position,
                kind="strength",
                text=text,
                provider="google",
                model_id="gemini-flash-eu-01",
                model_version="2026-09",
                prompt_id="assessment",
                prompt_version="3",
                generated_at=datetime(2026, 10, 14, 9, 42, tzinfo=UTC),
                status=status,
            )
        )
        db.commit()


def pdf(client: TestClient, token: str, run_id: object, query: str = "") -> Any:
    response = send_with_session(client, "GET", f"/runs/{run_id}/pdf{query}", token)
    if response.status_code == 503 and not os.environ.get("CI"):
        pytest.skip("WeasyPrint's system libraries (Pango) are not installed here")
    return response


def test_the_member_downloads_the_card_with_a_safe_file_name(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = finished_run(engine, user.organisation_id, "Acme Supplies SA")
    add_statement(engine, user.organisation_id, run_id, "Kept statement.")
    add_statement(engine, user.organisation_id, run_id, "Deleted statement.", "deleted", 1)

    response = pdf(client, token, run_id)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="supplier-card-acme-supplies-sa-')
    assert disposition.endswith('.pdf"')
    assert response.headers["cache-control"] == "no-store"
    assert response.content.startswith(b"%PDF")
    text = flat_text_of(response.content)
    assert "Kept statement." in text and "Deleted statement." not in text
    assert "supplier profile" in text.lower()
    assert "[Disclaimer: to be supplied by the owner]" in text
    assert metadata_of(response.content)["/aigeneratedcontent"] == "true"


def test_the_language_defaults_to_english_and_french_is_available(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = finished_run(engine, user.organisation_id, "Acme Supplies SA")

    default = pdf(client, token, run_id)
    french = pdf(client, token, run_id, "?lang=fr")

    assert "No public evidence found" in flat_text_of(default.content)
    assert "Aucune preuve publique trouvée" in flat_text_of(french.content)
    assert metadata_of(french.content)["/contentlanguage"] == "fr"


def test_another_language_is_a_validation_error(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = finished_run(engine, user.organisation_id, "Acme Supplies SA")

    response = send_with_session(client, "GET", f"/runs/{run_id}/pdf?lang=de", token)

    assert response.status_code == 422
    assert_matches_contract(response, "/runs/{id}/pdf", "get")


def test_another_organisations_run_an_unknown_run_and_the_administrator_get_the_same_404(
    client: TestClient, engine: Engine
) -> None:
    owner = create_organisation(engine)
    run_id = finished_run(engine, owner, "Distinctive Owner SA")
    member = create_user(engine)
    administrator = create_user(engine, role="admin")

    unknown = pdf(client, create_session(engine, member.id), uuid.uuid4())
    foreign = pdf(client, create_session(engine, member.id), run_id)
    admin = pdf(client, create_session(engine, administrator.id), run_id)

    assert unknown.status_code == foreign.status_code == admin.status_code == 404
    assert foreign.json() == unknown.json() == admin.json()
    assert_matches_contract(foreign, "/runs/{id}/pdf", "get")
    assert b"Distinctive" not in foreign.content


def test_the_pdf_requires_a_session(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    run_id = finished_run(engine, user.organisation_id, "Acme Supplies SA")

    response = client.get(f"/runs/{run_id}/pdf")

    assert response.status_code == 401
    assert_matches_contract(response, "/runs/{id}/pdf", "get")


@pytest.mark.parametrize(
    "status", ["running", "queued", "paused", "failed", "insufficient_sources"]
)
def test_a_run_without_a_finished_profile_answers_409(
    client: TestClient, engine: Engine, status: str
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = create_run(engine, user.organisation_id, status=status, enqueue=False)

    response = send_with_session(client, "GET", f"/runs/{run_id}/pdf", token)

    assert response.status_code == 409
    assert_matches_contract(response, "/runs/{id}/pdf", "get")


def test_a_natural_person_card_says_not_assessed(client: TestClient, engine: Engine) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = finished_run(engine, user.organisation_id, "Solo Founder")
    person = create_identity(engine, user.organisation_id, "Solo Founder", natural_person=True)
    with Session(engine) as db:
        db.execute(update(ProfileRun).where(ProfileRun.id == run_id).values(identity_id=person))
        db.commit()

    text = flat_text_of(pdf(client, token, run_id).content)

    assert "not assessed: natural-person business" in text.lower()
    assert "Procurement recommendations" not in text


def test_the_file_name_is_ascii_whatever_the_supplier_name() -> None:
    assert safe_filename("Société Générale d’Œuvres", "20261105") == (
        "supplier-card-societe-generale-duvres-20261105.pdf"
    )
    for hostile in ('../../etc/passwd"\r\nX-Evil: 1', "<script>", "日本語", "", None):
        name = safe_filename(hostile, "20261105")
        assert name.isascii() and "/" not in name and '"' not in name and "\n" not in name
        assert name.endswith("-20261105.pdf")


def test_the_disclaimer_comes_from_the_configured_content_file(
    engine: Engine, database_url: str, tmp_path: Path
) -> None:
    file = tmp_path / "disclaimer.json"
    file.write_text(json.dumps({"en": "OWNER TEXT EN", "fr": "TEXTE PROPRIÉTAIRE FR"}))
    client = make_client(
        settings=Settings(
            database_url=database_url,
            allowed_origins=(LOCAL_ORIGIN,),
            pdf_disclaimer_file=str(file),
        ),
        engine=engine,
    )
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = finished_run(engine, user.organisation_id, "Acme Supplies SA")

    english = flat_text_of(pdf(client, token, run_id).content)
    french = flat_text_of(pdf(client, token, run_id, "?lang=fr").content)

    assert "OWNER TEXT EN" in english and "[Disclaimer" not in english
    assert "TEXTE PROPRIÉTAIRE FR" in french


def test_an_unreadable_disclaimer_file_answers_503_without_a_path(
    engine: Engine, database_url: str, tmp_path: Path
) -> None:
    client = make_client(
        settings=Settings(
            database_url=database_url,
            allowed_origins=(LOCAL_ORIGIN,),
            pdf_disclaimer_file=str(tmp_path / "missing.json"),
        ),
        engine=engine,
    )
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = finished_run(engine, user.organisation_id, "Acme Supplies SA")

    response = send_with_session(client, "GET", f"/runs/{run_id}/pdf", token)

    assert response.status_code == 503
    assert str(tmp_path) not in response.text
    assert_matches_contract(response, "/runs/{id}/pdf", "get")


def test_the_pdf_has_more_than_one_page_for_a_long_profile(
    client: TestClient, engine: Engine
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = finished_run(engine, user.organisation_id, "Acme Supplies SA")
    for index in range(30):
        add_statement(
            engine,
            user.organisation_id,
            run_id,
            f"Statement {index} " + "word " * 50,
            position=index,
        )
    add_fact(engine, user.organisation_id, run_id, "employee_count", "480")

    response = pdf(client, token, run_id)

    assert len(PdfReader(io.BytesIO(response.content)).pages) >= 3

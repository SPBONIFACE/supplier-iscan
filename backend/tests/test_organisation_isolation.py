"""Organisation isolation (#10; spec, Security model): the shared scope and the shared test helper,
applied to GET /organisation and to a test-only organisation-owned resource ("notes").
"""

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated

import pytest
from fastapi import APIRouter, Response, status
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import Engine, MetaData, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.auth.bootstrap import DEFAULT_ORGANISATION_NAME, ensure_local_administrator
from app.auth.dependencies import CurrentPrincipal, Principal
from app.config import Settings
from app.db import NAMING_CONVENTION, Base, DbSession, utc_now
from app.errors import NOT_FOUND, not_found, parse_resource_id
from app.main import create_app
from app.models import Organisation, OrganisationOwned, User
from app.organisations.scope import OrganisationScope, OrganisationScoped
from tests.auth_support import send_with_session
from tests.factories import create_organisation, create_session, create_user
from tests.isolation_support import OwnedResource, OwnerOrganisation, assert_organisation_isolation
from tests.support import BASE_URL

# --- A test-only organisation-owned resource, on its own MetaData (not in the migrations) ------


class _TestBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# A copy of the organisations table, so that the foreign key resolves; never created or dropped.
Base.metadata.tables["organisations"].to_metadata(_TestBase.metadata)


class Note(OrganisationOwned, _TestBase):
    __tablename__ = "test_isolation_notes"

    text: Mapped[str] = mapped_column(String(200))


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class NoteOut(BaseModel):
    id: uuid.UUID
    text: str


notes = APIRouter(prefix="/test-notes")


@notes.post("", status_code=status.HTTP_201_CREATED, response_model=NoteOut)
def create_note(body: NoteIn, scope: OrganisationScoped, db: DbSession) -> NoteOut:
    note = scope.new(Note, text=body.text)
    db.add(note)
    db.commit()
    return NoteOut(id=note.id, text=note.text)


@notes.get("", response_model=list[NoteOut])
def list_notes(scope: OrganisationScoped, db: DbSession) -> list[NoteOut]:
    rows = db.scalars(scope.select(Note).order_by(Note.text)).all()
    return [NoteOut(id=row.id, text=row.text) for row in rows]


@notes.get("/{id}", response_model=NoteOut)
def get_note(id: str, scope: OrganisationScoped, db: DbSession) -> NoteOut:
    note = scope.get(db, Note, id)
    return NoteOut(id=note.id, text=note.text)


@notes.patch("/{id}", response_model=NoteOut)
def update_note(id: str, body: NoteIn, scope: OrganisationScoped, db: DbSession) -> NoteOut:
    note = scope.get(db, Note, id, for_update=True)
    note.text = body.text
    db.commit()
    return NoteOut(id=note.id, text=note.text)


@notes.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_note(id: str, scope: OrganisationScoped, db: DbSession) -> Response:
    note = scope.get(db, Note, id)
    db.execute(scope.delete(Note).where(Note.id == note.id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Deliberately unscoped, to prove that the shared helper catches a leak.
leaky = APIRouter(prefix="/test-leaky-notes")


@leaky.get("/{id}", response_model=NoteOut)
def get_leaky_note(id: str, principal: CurrentPrincipal, db: DbSession) -> NoteOut:
    note = db.get(Note, parse_resource_id(id))
    if note is None:
        raise not_found()
    return NoteOut(id=note.id, text=note.text)


@pytest.fixture(scope="module")
def _notes_table(_shared_engine: Engine) -> Iterator[None]:
    # Emptied with the other tables after each test: TRUNCATE organisations CASCADE reaches it.
    tables = [_TestBase.metadata.tables[Note.__tablename__]]
    _TestBase.metadata.create_all(_shared_engine, tables=tables)
    yield
    _TestBase.metadata.drop_all(_shared_engine, tables=tables)


@pytest.fixture
def notes_client(engine: Engine, settings: Settings, _notes_table: None) -> TestClient:
    application = create_app(settings, engine=engine)
    application.include_router(notes)
    application.include_router(leaky)
    return TestClient(application, base_url=BASE_URL, raise_server_exceptions=False)


def create_note_row(engine: Engine, organisation_id: uuid.UUID, text: str) -> uuid.UUID:
    with Session(engine) as db:
        note = Note(organisation_id=organisation_id, text=text)
        db.add(note)
        db.commit()
        return note.id


def make_note(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
    marker = f"Confidential note of {owner.name}"
    note_id = create_note_row(engine, owner.id, marker)
    return OwnedResource(f"/test-notes/{note_id}", f"/test-notes/{uuid.uuid4()}", marker)


def make_note_list(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
    marker = f"Listed note of {owner.name}"
    create_note_row(engine, owner.id, marker)
    return OwnedResource("/test-notes", None, marker)


def note_text(engine: Engine, note_id: uuid.UUID) -> str | None:
    with Session(engine) as db:
        return db.scalar(select(Note.text).where(Note.id == note_id))


# --- The shared helper on the test-only resource ----------------------------------------------


@pytest.mark.parametrize(
    ("method", "body"),
    [("GET", None), ("PATCH", {"text": "Overwritten by someone else"}), ("DELETE", None)],
)
def test_a_note_is_isolated(
    notes_client: TestClient, engine: Engine, method: str, body: dict[str, str] | None
) -> None:
    kwargs = {"json": body} if body else {}
    assert_organisation_isolation(notes_client, engine, method, make_note, **kwargs)


def test_the_note_list_is_isolated(notes_client: TestClient, engine: Engine) -> None:
    assert_organisation_isolation(notes_client, engine, "GET", make_note_list)


def test_the_helper_catches_an_unscoped_endpoint(notes_client: TestClient, engine: Engine) -> None:
    def make_leaky_note(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
        note_id = create_note_row(engine, owner.id, f"Leaked note of {owner.name}")
        path = "/test-leaky-notes"
        return OwnedResource(f"{path}/{note_id}", f"{path}/{uuid.uuid4()}", "Leaked note")

    with pytest.raises(AssertionError, match="leaks to the other organisation"):
        assert_organisation_isolation(notes_client, engine, "GET", make_leaky_note)


def test_another_organisations_note_answers_exactly_as_a_missing_one(
    notes_client: TestClient, engine: Engine
) -> None:
    member = create_user(engine)
    other_note = create_note_row(engine, create_organisation(engine, name="Other"), "Theirs")
    token = create_session(engine, member.id)

    for method, kwargs in (
        ("GET", {}),
        ("PATCH", {"json": {"text": "Mine now"}}),
        ("DELETE", {}),
    ):
        theirs = send_with_session(
            notes_client, method, f"/test-notes/{other_note}", token, **kwargs
        )
        missing = send_with_session(
            notes_client, method, f"/test-notes/{uuid.uuid4()}", token, **kwargs
        )
        malformed = send_with_session(
            notes_client, method, "/test-notes/not-an-id", token, **kwargs
        )
        for response in (theirs, missing, malformed):
            assert response.status_code == 404, method
            assert response.json() == {"detail": NOT_FOUND}
            assert response.headers.get("content-type") == missing.headers.get("content-type")
        assert theirs.content == missing.content == malformed.content

    assert note_text(engine, other_note) == "Theirs"  # neither updated nor deleted


def test_a_note_is_created_in_the_session_organisation_only(
    notes_client: TestClient, engine: Engine
) -> None:
    member = create_user(engine)
    other_organisation = create_organisation(engine, name="Other")
    token = create_session(engine, member.id)

    smuggled = send_with_session(
        notes_client,
        "POST",
        "/test-notes",
        token,
        json={"text": "x", "organisation_id": str(other_organisation)},
    )
    assert smuggled.status_code == 422  # no organisation id is accepted from the client

    created = send_with_session(notes_client, "POST", "/test-notes", token, json={"text": "Mine"})
    assert created.status_code == 201
    with Session(engine) as db:
        note = db.scalar(select(Note).where(Note.id == uuid.UUID(created.json()["id"])))
    assert note is not None
    assert note.organisation_id == member.organisation_id


def test_the_scope_refuses_an_organisation_id_from_the_caller() -> None:
    scope = OrganisationScope(principal=_principal(uuid.uuid4()))

    with pytest.raises(ValueError, match="organisation_id"):
        scope.new(Note, text="x", organisation_id=uuid.uuid4())
    assert scope.new(Note, text="x").organisation_id == scope.organisation_id


def test_scoped_queries_filter_on_the_session_organisation() -> None:
    organisation_id = uuid.uuid4()
    scope = OrganisationScope(principal=_principal(organisation_id))

    for statement in (scope.select(Note), scope.update(Note), scope.delete(Note)):
        compiled = statement.compile()
        assert "test_isolation_notes.organisation_id = " in str(compiled)
        assert organisation_id in compiled.params.values()


def _principal(organisation_id: uuid.UUID) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        email="someone@example.test",
        role="member",
        organisation_id=organisation_id,
        session_id=uuid.uuid4(),
    )


# --- Administrators -----------------------------------------------------------------------------


def test_the_local_administrator_reaches_the_default_organisation_only(
    notes_client: TestClient, engine: Engine, settings: Settings
) -> None:
    # Self-hosted first start (#8): the administrator is a member of the default organisation.
    with Session(engine, expire_on_commit=False) as db:
        local = Settings(
            database_url=settings.database_url,
            allowed_origins=settings.allowed_origins,
            admin_email="admin@example.test",
            admin_password="a long enough administrator password",  # noqa: S106 - test value
        )
        assert ensure_local_administrator(db, local)
        administrator = db.scalars(select(User).where(User.role == "admin")).one()
        default = db.scalars(select(Organisation)).one()
    assert default.name == DEFAULT_ORGANISATION_NAME
    assert administrator.organisation_id == default.id

    own_note = create_note_row(engine, default.id, "Default organisation content")
    other_note = create_note_row(engine, create_organisation(engine, name="Client"), "Client data")
    token = create_session(engine, administrator.id)

    own = send_with_session(notes_client, "GET", f"/test-notes/{own_note}", token)
    assert own.status_code == 200
    assert own.json()["text"] == "Default organisation content"

    theirs = send_with_session(notes_client, "GET", f"/test-notes/{other_note}", token)
    missing = send_with_session(notes_client, "GET", f"/test-notes/{uuid.uuid4()}", token)
    assert theirs.status_code == 404
    assert theirs.content == missing.content

    listed = send_with_session(notes_client, "GET", "/test-notes", token)
    assert [note["text"] for note in listed.json()] == ["Default organisation content"]

    organisation = send_with_session(notes_client, "GET", "/organisation", token)
    assert organisation.json()["name"] == DEFAULT_ORGANISATION_NAME


# --- GET /organisation ----------------------------------------------------------------------------


def make_own_organisation(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
    return OwnedResource("/organisation", None, owner.name)


def test_get_organisation_is_isolated(client: TestClient, engine: Engine) -> None:
    assert_organisation_isolation(client, engine, "GET", make_own_organisation)


def test_get_organisation_returns_the_members_own_organisation(
    client: TestClient, engine: Engine
) -> None:
    with Session(engine) as db:
        organisation = Organisation(
            name="Acme Buyers",
            status="active",
            seat_limit=5,
            profile_quota=40,
            access_period_days=30,
            access_ends_at=utc_now() + timedelta(days=30),
        )
        db.add(organisation)
        db.commit()
        organisation_id = organisation.id
    create_organisation(engine, name="Somebody Else", seat_limit=99)
    member = create_user(engine, organisation_id=organisation_id)

    response = send_with_session(client, "GET", "/organisation", create_session(engine, member.id))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "name",
        "status",
        "seat_limit",
        "profile_quota",
        "profiles_remaining",
        "comparison_max_profiles",
        "run_refusal_reason",
        "access_ends_at",
    }
    assert body["name"] == "Acme Buyers"
    assert body["status"] == "active"
    assert body["seat_limit"] == 5
    assert body["profile_quota"] == 40
    assert body["access_ends_at"] is not None
    assert "Somebody Else" not in response.text

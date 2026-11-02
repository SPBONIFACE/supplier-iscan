"""/identity and /identity-sessions (openapi.yaml, tag `identity`).

Every endpoint is scoped to the caller's organisation (`OrganisationScoped`): another
organisation's session answers the same 404 as an unknown id. The member decides: the only way a
session ends is `POST .../confirm`.
"""

import threading
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.db import DbSession, utc_now
from app.errors import InvalidField
from app.http_client import FetchError, normalise_url
from app.identity.agent import IdentityAgent, hint_url
from app.identity.services import IdentityServices, build_identity_services
from app.identity.strings import disclosure_text
from app.models import IdentitySession, SupplierIdentity
from app.organisations.scope import OrganisationScoped
from app.redaction import gate_for
from app.registries.text import has_visible_text, normalise_text

router = APIRouter(tags=["identity"])

ALREADY_CONFIRMED = "This identity is already confirmed."
_build_lock = threading.Lock()

Language = Literal["en", "fr"]


class IdentityDisclosureOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language
    text: str


class IdentityHintsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website: str | None = Field(default=None, max_length=2000)
    country: str | None = Field(default=None, max_length=100)
    sector: str | None = Field(default=None, max_length=200)


class IdentitySessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=300)
    hints: IdentityHintsIn | None = None
    profile_language: Language
    ui_language: Language


class IdentityMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=2000)


class IdentityWebsiteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website: str = Field(max_length=2000)


class IdentityConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str


class IdentifierOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme: str
    value: str


class IdentityCandidateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    legal_name: str
    legal_form: str | None
    website: str | None
    country: str | None
    sector: str | None
    description: str | None
    found_in: list[Literal["gleif", "wikidata", "website", "web"]]
    identifiers: list[IdentifierOut]


class IdentityCandidateListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[IdentityCandidateOut]


class IdentityTurnOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    role: Literal["assistant", "user"]
    kind: Literal["disclosure", "text", "proposal", "notice", "website_rejected", "error"]
    text: str
    candidate: IdentityCandidateOut | None
    created_at: datetime


class IdentityHintsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website: str | None
    country: str | None
    sector: str | None


class RegistryStatusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gleif: Literal["ok", "unreachable"]
    wikidata: Literal["ok", "unreachable"]


class IdentitySessionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    name: str
    hints: IdentityHintsOut
    profile_language: Language
    status: Literal["open", "confirmed"]
    turns: list[IdentityTurnOut]
    registries: RegistryStatusOut
    identity_id: uuid.UUID | None
    created_at: datetime


class IdentityConfirmedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_id: uuid.UUID
    candidate: IdentityCandidateOut
    natural_person: bool
    confirmed_at: datetime


def _session_out(session: IdentitySession) -> IdentitySessionOut:
    registries = {"gleif": "ok", "wikidata": "ok", **session.registries}
    hints = {"website": None, "country": None, "sector": None, **session.hints}
    return IdentitySessionOut.model_validate(
        {
            "id": session.id,
            "name": session.name,
            "hints": hints,
            "profile_language": session.profile_language,
            "status": "confirmed" if session.identity_id else "open",
            "turns": session.transcript,
            "registries": registries,
            "identity_id": session.identity_id,
            "created_at": session.created_at,
        }
    )


def _services(request: Request) -> IdentityServices:
    services: IdentityServices | None = getattr(request.app.state, "identity_services", None)
    if services is None:
        with _build_lock:
            services = getattr(request.app.state, "identity_services", None)
            if services is None:
                services = build_identity_services()
                request.app.state.identity_services = services
    return services


def _agent(request: Request) -> IdentityAgent:
    state = request.app.state
    return IdentityAgent(
        state.prompt_set, state.providers, _services(request), gate_for(state.database)
    )


def _conflict() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=ALREADY_CONFIRMED)


def _open_session(
    scope: OrganisationScoped, db: DbSession, session_id: str, *, lock: bool = False
) -> IdentitySession:
    session = scope.get(db, IdentitySession, session_id, for_update=lock)
    if session.identity_id is not None:
        raise _conflict()
    return session


def _hints(body: IdentityHintsIn | None) -> dict[str, str | None]:
    hints: dict[str, str | None] = {"website": None, "country": None, "sector": None}
    if body is None:
        return hints
    if body.website and body.website.strip():
        try:
            hints["website"] = hint_url(body.website)
        except FetchError:
            raise InvalidField("hints.website", "Enter a valid website address.") from None
    country = (body.country or "").strip()
    if country:
        if len(country) != 2 or not country.isascii() or not country.isalpha():
            raise InvalidField("hints.country", "Use a two-letter country code (ISO 3166-1).")
        hints["country"] = country.upper()
    sector = normalise_text(body.sector or "")
    hints["sector"] = sector if sector and has_visible_text(sector) else None
    return hints


@router.get("/identity/disclosure", response_model=IdentityDisclosureOut)
def get_disclosure(language: Language, scope: OrganisationScoped) -> IdentityDisclosureOut:
    return IdentityDisclosureOut(language=language, text=disclosure_text(language))


@router.post(
    "/identity-sessions", status_code=status.HTTP_201_CREATED, response_model=IdentitySessionOut
)
def create_session(
    body: IdentitySessionCreate, scope: OrganisationScoped, db: DbSession, request: Request
) -> IdentitySessionOut:
    name = normalise_text(body.name)
    if not name or not has_visible_text(name):
        raise InvalidField("name", "Enter the supplier name.")
    session = scope.new(
        IdentitySession,
        created_by=scope.principal.user_id,
        name=name,
        hints=_hints(body.hints),
        profile_language=body.profile_language,
        ui_language=body.ui_language,
        transcript=[],
        candidates=[],
        registries={},
        last_message_at=utc_now(),
    )
    _agent(request).start(session)
    db.add(session)
    db.commit()
    return _session_out(session)


@router.get("/identity-sessions/{id}", response_model=IdentitySessionOut)
def get_session(id: str, scope: OrganisationScoped, db: DbSession) -> IdentitySessionOut:
    return _session_out(scope.get(db, IdentitySession, id))


@router.post("/identity-sessions/{id}/messages", response_model=IdentitySessionOut)
def send_message(
    id: str, body: IdentityMessageIn, scope: OrganisationScoped, db: DbSession, request: Request
) -> IdentitySessionOut:
    session = _open_session(scope, db, id, lock=True)
    text = body.text.strip()
    if not text or not has_visible_text(text):
        raise InvalidField("text", "Write a message.")
    _agent(request).correct(session, text)
    db.commit()
    return _session_out(session)


@router.get("/identity-sessions/{id}/candidates", response_model=IdentityCandidateListOut)
def list_candidates(id: str, scope: OrganisationScoped, db: DbSession) -> IdentityCandidateListOut:
    session = scope.get(db, IdentitySession, id)
    others = [
        entry["candidate"]
        for entry in session.candidates
        if entry["candidate"]["id"] != session.current_candidate_id
    ]
    return IdentityCandidateListOut.model_validate({"candidates": others})


@router.post("/identity-sessions/{id}/website", response_model=IdentitySessionOut)
def submit_website(
    id: str, body: IdentityWebsiteIn, scope: OrganisationScoped, db: DbSession, request: Request
) -> IdentitySessionOut:
    session = _open_session(scope, db, id, lock=True)
    raw = body.website.strip()
    try:
        normalise_url(raw, assume_https=True)
    except FetchError:
        raise InvalidField("website", "Enter a valid website address.") from None
    _agent(request).use_website(session, raw)
    db.commit()
    return _session_out(session)


def _stored_address(entry: dict[str, Any]) -> str | None:
    """The registry address to keep: a natural person's only, and only if the registry gave one."""
    address = entry.get("registered_address") if entry["natural_person"] else None
    return str(address)[:500] if address else None


@router.post("/identity-sessions/{id}/confirm", response_model=IdentityConfirmedOut)
def confirm_identity(
    id: str, body: IdentityConfirmIn, scope: OrganisationScoped, db: DbSession
) -> IdentityConfirmedOut:
    session = _open_session(scope, db, id, lock=True)
    entry: dict[str, Any] | None = next(
        (item for item in session.candidates if item["candidate"]["id"] == body.candidate_id),
        None,
    )
    if entry is None:
        raise InvalidField("candidate_id", "Choose one of the candidates of this session.")
    candidate = entry["candidate"]
    now = utc_now()
    identity = scope.new(
        SupplierIdentity,
        legal_name=candidate["legal_name"][:300],
        website=candidate["website"],
        country=(candidate["country"] or None) and candidate["country"][:100],
        sector=(candidate["sector"] or None) and candidate["sector"][:200],
        registry_ids={key: entry[key] for key in ("lei", "wikidata_id") if entry.get(key)},
        natural_person=bool(entry["natural_person"]),
        # Only for a natural person, and only what the registry gave; never in a response.
        registered_address=_stored_address(entry),
        confirmed_by=scope.principal.user_id,
        confirmed_at=now,
    )
    db.add(identity)
    db.flush()
    session.identity_id = identity.id
    session.current_candidate_id = candidate["id"]
    db.commit()
    return IdentityConfirmedOut.model_validate(
        {
            "identity_id": identity.id,
            "candidate": candidate,
            "natural_person": identity.natural_person,
            "confirmed_at": now,
        }
    )

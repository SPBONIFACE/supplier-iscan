"""Every route of the application declares its access (#10; app/auth/access.py):
organisation-scoped, administrator-only, public, or the signed-in user's own account. A route that
declares none of them fails here, and no non-administrator route accepts an organisation id from
the client.
"""

from collections.abc import Callable, Iterator, Sequence
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from pydantic import BaseModel
from starlette.routing import BaseRoute

from app.auth.access import OWN_ACCOUNT, PUBLIC, own_account_endpoint, public_endpoint
from app.auth.dependencies import CurrentPrincipal, require_administrator, require_session
from app.config import Settings
from app.main import create_app
from app.organisations.scope import OrganisationScoped, require_organisation_scope
from tests.support import LOCAL_ORIGIN

ORGANISATION_ID = "organisation_id"


def _calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from _calls(dependency)


def _parameters(dependant: Dependant) -> Iterator[str]:
    for param in (
        *dependant.path_params,
        *dependant.query_params,
        *dependant.header_params,
        *dependant.cookie_params,
    ):
        yield param.alias
    for param in dependant.body_params:
        yield param.alias
        annotation = param.field_info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            yield from (field.alias or name for name, field in annotation.model_fields.items())
    for dependency in dependant.dependencies:
        yield from _parameters(dependency)


def routes_of(routes: Sequence[BaseRoute]) -> Iterator[RouteContext]:
    """Every route as the application serves it, included routers flattened, with the router's
    own dependencies merged into the route's.
    """
    yield from iter_route_contexts(routes)


def access_of(route: RouteContext) -> str | None:
    calls = set(_calls(route.dependant))
    if require_administrator in calls:
        return "administrator"
    if require_organisation_scope in calls:
        return "organisation"
    if public_endpoint in calls and require_session not in calls:
        return "public"
    if own_account_endpoint in calls and require_session in calls:
        return "own account"
    return None


def problems(routes: Sequence[BaseRoute]) -> list[str]:
    found: list[str] = []
    for route in routes_of(routes):
        if not isinstance(route.original_route, APIRoute):
            found.append(f"{route.path} is not an API route")
            continue
        name = f"{sorted(route.methods or ())} {route.path}"
        access = access_of(route)
        if access is None:
            found.append(f"{name} declares no access (scope, administrator, public, own account)")
        elif access != "administrator" and ORGANISATION_ID in set(_parameters(route.dependant)):
            found.append(f"{name} accepts an organisation id from the client")
    return found


def application() -> FastAPI:
    return create_app(Settings(database_url=None, allowed_origins=(LOCAL_ORIGIN,)))


def test_every_route_declares_its_access() -> None:
    routes = application().routes

    assert len(list(routes_of(routes))) >= 12
    assert problems(routes) == []


def test_member_api_routes_use_the_organisation_scope() -> None:
    access = {
        route.path: access_of(route)
        for route in routes_of(application().routes)
        if isinstance(route.original_route, APIRoute)
    }

    assert access["/organisation"] == "organisation"
    assert access["/health"] == "public"
    assert access["/auth/login"] == "public"
    assert access["/auth/me"] == "own account"
    assert access["/users/{id}"] == "own account"
    assert access["/profile-definition"] == "own account"
    assert access["/admin/organisations"] == "administrator"


def test_an_unmarked_or_mismarked_route_fails_the_check() -> None:
    class Smuggled(BaseModel):
        organisation_id: str

    router = APIRouter()

    @router.get("/unmarked")
    def unmarked(principal: CurrentPrincipal) -> None: ...

    @router.get("/public-but-signed-in", dependencies=[PUBLIC])
    def public_but_signed_in(principal: CurrentPrincipal) -> None: ...

    @router.get("/own-account-without-session", dependencies=[OWN_ACCOUNT])
    def own_account_without_session() -> None: ...

    @router.get("/scoped-with-query")
    def scoped_with_query(scope: OrganisationScoped, organisation_id: str) -> None: ...

    @router.post("/scoped-with-body")
    def scoped_with_body(scope: OrganisationScoped, body: Smuggled) -> None: ...

    @router.get("/fine")
    def fine(scope: OrganisationScoped) -> None: ...

    found = problems(router.routes)

    assert len(found) == 5, found
    assert not any("/fine" in problem for problem in found)

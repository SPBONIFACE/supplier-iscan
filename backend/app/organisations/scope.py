"""Organisation isolation (spec, Security model: access rules). The one way a member endpoint
reaches an organisation-owned table:

    from app.organisations.scope import OrganisationScoped

    @router.get("/things/{id}")
    def get_thing(id: str, scope: OrganisationScoped, db: DbSession) -> ThingOut:
        thing = scope.get(db, Thing, id)          # 404 when absent or not the caller's
        ...

    @router.get("/things")
    def list_things(scope: OrganisationScoped, db: DbSession) -> ThingList:
        rows = db.scalars(scope.select(Thing).order_by(Thing.created_at)).all()

    @router.post("/things")
    def create_thing(body: ThingCreate, scope: OrganisationScoped, db: DbSession) -> ThingOut:
        thing = scope.new(Thing, name=body.name)  # organisation_id from the session, never the body

The organisation always comes from the session; no member endpoint takes it from the client. A
resource of another organisation answers exactly the same 404 as an id that does not exist.

An administrator is scoped like any member, to the organisation they belong to: an administrator
never reaches the content of an organisation they are not a member of. The local administrator of
a self-hosted instance belongs to the default organisation and so reaches that one, and only that
one (owner decision, 27 Oct 2026). Administrator operations on organisations themselves
(`/admin/...`) depend on `require_administrator` instead and never return content.

An organisation-owned model inherits `app.models.OrganisationOwned`. A cache that holds personal
data is keyed by `scope.organisation_id`, never shared between organisations (spec, Data
protection).
"""

import uuid
from dataclasses import dataclass
from typing import Annotated, Any, TypeVar, cast

from fastapi import Depends
from sqlalchemy import Delete, Select, Update, delete, select, update
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentPrincipal, Principal
from app.errors import not_found, parse_resource_id
from app.models import OrganisationOwned

Owned = TypeVar("Owned", bound=OrganisationOwned)


@dataclass(frozen=True)
class OrganisationScope:
    """The session's organisation, and query builders restricted to it."""

    principal: Principal

    @property
    def organisation_id(self) -> uuid.UUID:
        return self.principal.organisation_id

    def select(self, model: type[Owned]) -> Select[tuple[Owned]]:
        return select(model).where(model.organisation_id == self.organisation_id)

    def update(self, model: type[Owned]) -> Update:
        return update(model).where(model.organisation_id == self.organisation_id)

    def delete(self, model: type[Owned]) -> Delete:
        return delete(model).where(model.organisation_id == self.organisation_id)

    def get(
        self, db: Session, model: type[Owned], raw_id: str | uuid.UUID, *, for_update: bool = False
    ) -> Owned:
        """The caller's resource with this id, or the one 404 (absent, malformed or not theirs)."""
        resource_id = raw_id if isinstance(raw_id, uuid.UUID) else parse_resource_id(raw_id)
        query = self.select(model).where(model.id == resource_id)
        if for_update:
            query = query.with_for_update()
        found = db.scalar(query)
        if found is None:
            raise not_found()
        return found

    def new(self, model: type[Owned], **values: Any) -> Owned:
        """A new row of the caller's organisation (not added to the session)."""
        if "organisation_id" in values:
            raise ValueError("organisation_id comes from the session, never from the caller")
        # Mapped models take their columns as keyword arguments; the mixin alone does not say so.
        row: Owned = cast(Any, model)(organisation_id=self.organisation_id, **values)
        return row


def require_organisation_scope(principal: CurrentPrincipal) -> OrganisationScope:
    """401 without a valid session; otherwise the scope of the session's organisation."""
    return OrganisationScope(principal)


# Type of an endpoint parameter that receives the caller's organisation scope.
OrganisationScoped = Annotated[OrganisationScope, Depends(require_organisation_scope)]

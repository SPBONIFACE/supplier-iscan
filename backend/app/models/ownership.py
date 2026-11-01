"""The mixin of every organisation-owned model (spec, Data model & ownership). Member endpoints
reach these tables only through `app.organisations.scope.OrganisationScope`.
"""

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column


class OrganisationOwned:
    """A UUID `id` and the owning `organisation_id`."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True
    )

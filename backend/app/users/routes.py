"""GET /users/{id} (openapi.yaml, tag `users`; spec Security model, access rules).

A member reads only their own record: any other id answers the same 404 as an id that does not
exist. An administrator reads any user record.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.auth.access import OWN_ACCOUNT
from app.auth.dependencies import CurrentPrincipal
from app.db import DbSession
from app.errors import not_found, parse_resource_id
from app.models import User

router = APIRouter(prefix="/users", tags=["users"], dependencies=[OWN_ACCOUNT])


class UserOut(BaseModel):
    """Mirrors components/schemas/User. Never the password hash."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    organisation_id: uuid.UUID
    email: str
    role: Literal["admin", "member"]
    created_at: datetime
    last_login_at: datetime | None


@router.get("/{id}", response_model=UserOut)
def get_user(id: str, principal: CurrentPrincipal, db: DbSession) -> UserOut:
    user_id = parse_resource_id(id)
    if principal.role != "admin" and user_id != principal.user_id:
        # Not looked up at all: the answer cannot depend on whether the user exists.
        raise not_found()
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise not_found()
    return UserOut.model_validate(
        {
            "id": user.id,
            "organisation_id": user.organisation_id,
            "email": user.email,
            "role": user.role,
            "created_at": user.created_at,
            "last_login_at": user.last_login_at,
        }
    )

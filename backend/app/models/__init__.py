"""All models. Importing this package registers every table on `app.db.Base.metadata`,
which Alembic compares against the migrations. A new model module is imported here.
"""

from app.models.accounts import Organisation, User, UserSession
from app.models.invitations import Invitation
from app.models.llm_usage import LlmUsage
from app.models.providers import ProviderConfig
from app.models.usage import UsageEvent

__all__ = [
    "Invitation",
    "LlmUsage",
    "Organisation",
    "ProviderConfig",
    "UsageEvent",
    "User",
    "UserSession",
]

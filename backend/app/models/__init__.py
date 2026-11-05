"""All models. Importing this package registers every table on `app.db.Base.metadata`,
which Alembic compares against the migrations. A new model module is imported here.
"""

from app.models.accounts import Organisation, User, UserSession
from app.models.assessment import AssessmentItem
from app.models.buyer import BuyerInput
from app.models.crawl import CrawlPermission, SuppressionEntry
from app.models.facts import Fact
from app.models.failures import RunFailure
from app.models.identity import IdentitySession
from app.models.invitations import Invitation
from app.models.llm_usage import LlmUsage
from app.models.ownership import OrganisationOwned
from app.models.providers import ProviderConfig
from app.models.runs import Job, ProfileRun, SupplierIdentity
from app.models.sources import Source
from app.models.usage import UsageEvent

__all__ = [
    "AssessmentItem",
    "BuyerInput",
    "CrawlPermission",
    "Fact",
    "IdentitySession",
    "Invitation",
    "Job",
    "LlmUsage",
    "Organisation",
    "OrganisationOwned",
    "ProfileRun",
    "ProviderConfig",
    "RunFailure",
    "Source",
    "SupplierIdentity",
    "SuppressionEntry",
    "UsageEvent",
    "User",
    "UserSession",
]

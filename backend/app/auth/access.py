"""Explicit access marks for routes that do not use the organisation scope.

Every route of the application declares how it is protected; `tests/test_route_access.py` fails
for a route that declares nothing. A route is one of:

- organisation-scoped: depends on `app.organisations.scope.OrganisationScoped` (every member
  endpoint on organisation-owned data);
- administrator-only: depends on `app.auth.dependencies.require_administrator`;
- public: `dependencies=[PUBLIC]`, no session (health, login, invitation links);
- own account: `dependencies=[OWN_ACCOUNT]` plus `CurrentPrincipal`, for the signed-in user's own
  session and user record, which hold no organisation content.

The marks are no-op dependencies: they only make the intent visible to that test.
"""

from fastapi import Depends


def public_endpoint() -> None:
    """Mark: reachable without a session."""


def own_account_endpoint() -> None:
    """Mark: the signed-in user's own account only (session, own user record)."""


PUBLIC = Depends(public_endpoint)
OWN_ACCOUNT = Depends(own_account_endpoint)

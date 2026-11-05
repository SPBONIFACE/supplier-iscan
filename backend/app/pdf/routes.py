"""GET /runs/{id}/pdf (openapi.yaml, tag `runs`): the supplier card as a PDF, generated on request.

The run is the caller's (the #10 scope: another organisation's run, an unknown id and the
administrator all answer the one 404). The file is built from what the card endpoints return and is
never stored; no model is called; nothing of the supplier's content is logged.
"""

import re
import unicodedata
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from app.buyer.routes import get_buyer_inputs
from app.db import DbSession, utc_now
from app.models import Organisation, ProfileRun
from app.organisations.scope import OrganisationScoped
from app.pdf.disclaimer import DisclaimerError, disclaimer_text
from app.pdf.render import CardInput, PdfUnavailable, render_pdf
from app.runs.routes import _one, get_assessment, hide_names, list_facts

router = APIRouter(prefix="/runs", tags=["runs"])

IN_PROGRESS_STATUSES = ("queued", "running", "paused")
IN_PROGRESS = "The run is still in progress."
NO_PROFILE = "The run ended without a profile, so there is no supplier card to export."
UNAVAILABLE = "The PDF cannot be generated right now. Please try again in a few minutes."


def safe_filename(name: str | None, day: str) -> str:
    """An ASCII file name (letters, digits and hyphens) built from the supplier name."""
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:60].strip("-")
    return f"supplier-card-{slug or 'supplier'}-{day}.pdf"


@router.get(
    "/{id}/pdf", response_class=Response, responses={200: {"content": {"application/pdf": {}}}}
)
def get_run_pdf(
    id: str,
    scope: OrganisationScoped,
    db: DbSession,
    request: Request,
    lang: Annotated[Literal["en", "fr"], Query()] = "en",
) -> Response:
    run = scope.get(db, ProfileRun, id)  # the one 404 for an unknown or another organisation's run
    if run.status in IN_PROGRESS_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=IN_PROGRESS)
    if run.status not in ("completed", "partial"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NO_PROFILE)

    settings = request.app.state.settings
    organisation = db.scalar(
        select(Organisation.name).where(Organisation.id == scope.organisation_id)
    )
    now = utc_now()
    try:
        card = CardInput(
            run=_one(db, scope, run, hide_names(request, scope)),
            facts=list_facts(id, scope, db, request).items,
            definition=request.app.state.profile_definition,
            assessment=get_assessment(id, scope, db, request),
            buyer_inputs=get_buyer_inputs(id, scope, db),
            organisation_name=organisation or "",
            generated_at=now,
            lang=lang,
            disclaimer=disclaimer_text(settings, lang),
        )
        content = render_pdf(card)
    except (PdfUnavailable, DisclaimerError):
        # The message is generic: no path, no content.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=UNAVAILABLE) from None

    filename = safe_filename(card.run.supplier_name, now.strftime("%Y%m%d"))
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )

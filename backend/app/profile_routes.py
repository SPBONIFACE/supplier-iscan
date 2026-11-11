"""GET /profile-definition (openapi.yaml, tag `profile`): the active definition in one language."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict

from app.auth.access import OWN_ACCOUNT
from app.auth.dependencies import CurrentPrincipal
from app.profile_definition import FieldKind, Language, ProfileDefinition

router = APIRouter(tags=["profile"], dependencies=[OWN_ACCOUNT])


class FieldOut(BaseModel):
    """Mirrors components/schemas/ProfileField. The extraction hint is not exposed."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    kind: FieldKind
    certification: bool
    concerns_people: bool
    key_figure: bool
    header_detail: bool
    timeline: bool


class SectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    fields: list[FieldOut]


class ProfileDefinitionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hash: str
    language: Language
    sections: list[SectionOut]


def render(definition: ProfileDefinition, language: Language) -> ProfileDefinitionOut:
    return ProfileDefinitionOut(
        hash=definition.content_hash,
        language=language,
        sections=[
            SectionOut(
                id=section.id,
                label=section.labels[language],
                fields=[
                    FieldOut(
                        id=field.id,
                        label=field.labels[language],
                        kind=field.kind,
                        certification=field.certification,
                        concerns_people=field.concerns_people,
                        key_figure=field.key_figure,
                        header_detail=field.header_detail,
                        timeline=field.timeline,
                    )
                    for field in section.fields
                ],
            )
            for section in definition.sections
        ],
    )


@router.get("/profile-definition", response_model=ProfileDefinitionOut)
def get_profile_definition(
    request: Request,
    principal: CurrentPrincipal,
    language: Annotated[Literal["en", "fr"], Query()] = "en",
) -> ProfileDefinitionOut:
    del principal  # the session is the only requirement: the definition holds no organisation data
    return render(request.app.state.profile_definition, language)

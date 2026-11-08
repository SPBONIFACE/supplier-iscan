"""Typed input and output of the registry candidate search (spec F1, Integrations)."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.countries import normalise_code
from app.registries.text import has_visible_text, normalise_text

RegistryName = Literal["wikidata", "gleif"]
REGISTRY_NAMES: tuple[RegistryName, ...] = ("wikidata", "gleif")

MAX_NAME_LENGTH = 200
MAX_HINT_LENGTH = 200


class RegistrySearchQuery(BaseModel):
    """A supplier name and optional hints. The hints change the ranking only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(max_length=MAX_NAME_LENGTH)
    website_hint: str | None = Field(default=None, max_length=MAX_HINT_LENGTH)
    country_hint: str | None = Field(default=None, max_length=MAX_HINT_LENGTH)
    sector_hint: str | None = Field(default=None, max_length=MAX_HINT_LENGTH)

    @field_validator("name")
    @classmethod
    def _name_is_not_blank(cls, value: str) -> str:
        normalised = normalise_text(value)
        if not normalised or not has_visible_text(normalised):
            raise ValueError("the supplier name must not be empty")
        return normalised

    @field_validator("website_hint", "country_hint", "sector_hint")
    @classmethod
    def _blank_hint_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalise_text(value) or None


class RegistryCandidate(BaseModel):
    """One company as published by Wikidata and/or GLEIF. Registry public data only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    legal_name: str | None = None
    description: str | None = None
    website: str | None = None
    # ISO 3166-1 alpha-2 code, and the country's label when Wikidata provides it.
    country: str | None = None
    country_name: str | None = None

    @field_validator("country")
    @classmethod
    def _country_is_a_code(cls, value: str | None) -> str | None:
        """Always an upper-case code; anything else (a free-text name) is no country (#136)."""
        return normalise_code(value)

    industries: tuple[str, ...] = ()
    legal_form: str | None = None
    # ISO 20275 Entity Legal Form code, from GLEIF.
    legal_form_code: str | None = None
    registered_address: str | None = None
    wikidata_id: str | None = None
    lei: str | None = None
    # GLEIF entity status ("ACTIVE", "INACTIVE").
    lei_status: str | None = None
    registries: tuple[RegistryName, ...]

    @model_validator(mode="after")
    def _has_an_identifier(self) -> Self:
        if not self.wikidata_id and not self.lei:
            raise ValueError("a candidate has a Wikidata id, an LEI or both")
        if not self.registries:
            raise ValueError("a candidate names the registry it came from")
        return self


class RegistrySearchResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Ranked, best first.
    candidates: tuple[RegistryCandidate, ...]
    # Registries that were unreachable, timed out or answered with an error.
    failed_registries: tuple[RegistryName, ...]
    # True when no candidate could be found (in particular when both registries failed): the member
    # is offered to enter the website directly (spec F1).
    website_fallback_offered: bool

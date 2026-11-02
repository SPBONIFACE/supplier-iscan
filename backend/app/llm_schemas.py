"""Typed outputs of the LLM structuring role, shared by the features that use them.

`FieldExtraction` is the contract of spec § LLM features (F3): a value with its verbatim quote and
the id of the source it comes from, or the explicit status `not_found`. A provider answers with a
`FieldExtractionBatch` (structured-output APIs need an object at the root). The grounding check
that the quote really is in the source is #23; the provider contract tests (#12) check it on
recorded fixtures with exact matching.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FieldExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(min_length=1, max_length=200)
    status: Literal["found", "not_found"]
    value: str | None = Field(default=None, max_length=4000)
    quote: str | None = Field(default=None, max_length=4000)
    source_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _complete(self) -> Self:
        parts = (self.value, self.quote, self.source_id)
        if self.status == "found" and not all(part and part.strip() for part in parts):
            raise ValueError("a found field needs a value, a quote and a source_id")
        if self.status == "not_found" and any(part is not None for part in parts):
            raise ValueError("a not_found field has no value, quote or source_id")
        return self


class IdentityProposal(BaseModel):
    """The identity agent's answer (spec § LLM features, F1).

    `candidate_id` names one of the candidates given to the model; code ignores any other value.
    `search_name` and `country_hint` ask for a new registry search when the member's correction
    points to another company (for example "the French subsidiary"). `off_topic` marks a message
    that is not about identifying the supplier; the model then declines in `question_to_user`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str | None = Field(default=None, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)
    question_to_user: str | None = Field(default=None, max_length=1000)
    off_topic: bool = False
    search_name: str | None = Field(default=None, max_length=200)
    country_hint: str | None = Field(default=None, max_length=2)


class FieldExtractionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    extractions: list[FieldExtraction]

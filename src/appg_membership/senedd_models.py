from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

EndReason = Literal[
    "term_ended",
    "left_senedd",
    "no_longer_listed",
    "registration_closed",
]


class MembershipValidity(BaseModel):
    """
    Known bounds on membership, separate from the date of its first observation.

    Bounds are half-open. Unknown start dates remain unknown; an end date is a
    latest possible end, rather than evidence of continuous membership before it.
    """

    observed_on: date | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    end_reason: EndReason | None = None


class SeneddTerm(BaseModel):
    """
    Verified term boundaries and the earliest permitted CPG registration date.
    """

    model_config = ConfigDict(frozen=True)

    number: int = Field(ge=1)
    starts_on: date
    registration_opens_on: date
    ends_on: date | None = None
    evidence_url: HttpUrl

    @model_validator(mode="after")
    def check_dates(self) -> SeneddTerm:
        """
        Reject inconsistent configuration of term and registration boundaries.
        """
        if self.registration_opens_on < self.starts_on:
            raise ValueError("Registration cannot open before the term starts")
        if self.ends_on and self.ends_on <= self.registration_opens_on:
            raise ValueError("The term must end after registration opens")
        return self


class SeneddRegistration(BaseModel):
    """
    A source body registered in one term, with explicit verification evidence.
    """

    body_id: str
    term: int = Field(ge=1)
    evidence_url: HttpUrl
    verified: bool = False
    observed_on: date | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    end_reason: EndReason | None = None

    @property
    def id(self) -> str:
        """
        Identify a registration independently of its name and display language.
        """
        return f"senedd-{self.term}-{self.body_id}"

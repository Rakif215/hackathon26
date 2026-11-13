"""Synthetic-development review commands; supplied identity is not authentication."""

import json
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from hackathon26.listener.models import Contract


class ReviewRequest(Contract):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")
    reviewer: str = Field(min_length=1, max_length=100)
    decision: Literal["ACCEPTED", "OVERRIDDEN", "DEFERRED"]
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        if not self.reviewer.strip():
            raise ValueError("Reviewer must not be blank")
        if self.decision == "OVERRIDDEN" and not self.note.strip():
            raise ValueError("An override requires an explanation")
        if len(json.dumps(self.model_dump(), ensure_ascii=False)) > 2500:
            raise ValueError("Encoded review is too long for the audit record")
        return self


class ReviewResult(Contract):
    review_id: int
    consultation_id: int
    finding_id: int
    reviewer: str
    decision: Literal["ACCEPTED", "OVERRIDDEN", "DEFERRED"]
    note: str
    decided_at: AwareDatetime
    persisted: Literal[True] = True

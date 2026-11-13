"""Versioned listener contracts. Offsets are Python Unicode character indices."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TranscriptSegment(Contract):
    schema_version: Literal["1"]
    event_id: str = Field(min_length=1, max_length=128)
    consultation_id: str = Field(min_length=1, max_length=128)
    segment_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(strict=True, ge=1)
    sequence: int = Field(strict=True, ge=1)
    speaker: Literal["PATIENT", "DOCTOR", "UNKNOWN"]
    text: str = Field(min_length=1, max_length=4000)
    is_final: StrictBool
    source: Literal["script"]
    occurred_at: AwareDatetime

    @field_validator("text", "event_id", "consultation_id", "segment_id")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Must contain non-whitespace characters")
        return value


class Mention(Contract):
    raw_text: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    kind: Literal["NAME", "APPEARANCE", "INDICATION"]
    assertion: Literal["AFFIRMED", "NEGATED", "UNCERTAIN"]
    subject: Literal["PATIENT", "OTHER", "UNKNOWN"]
    temporal: Literal["CURRENT", "HISTORICAL", "UNKNOWN"]
    confidence_basis: str
    clarification: str
    needs_review: Literal[True] = True


class ListenerResult(Contract):
    schema_version: Literal["1"] = "1"
    processor_version: Literal["demo-rules-v1"] = "demo-rules-v1"
    event_id: str
    consultation_id: str
    segment_id: str
    revision: int
    sequence: int
    status: Literal["ANALYZED", "PROVISIONAL"]
    mentions: list[Mention]
    limitations: list[str]
    persisted: Literal[False] = False

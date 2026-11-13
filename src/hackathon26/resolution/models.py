"""Read-only medication candidate contracts."""

from datetime import date
from typing import Literal

from pydantic import Field

from hackathon26.listener.models import Contract, Mention, TranscriptSegment
from hackathon26.match_level import MatchLevel


class ResolveRequest(Contract):
    segment: TranscriptSegment
    as_of: date


class RecordedMedication(Contract):
    patient_med_id: int
    drug_id: int
    generic_name: str
    strength: str | None = None
    color: str | None = None
    shape: str | None = None
    imprint: str | None = None
    appearance_strength: str | None = None
    manufacturer: str | None = None
    appearance_source: str | None = None


class Candidate(RecordedMedication):
    match_level: Literal[MatchLevel.NAME_MATCH, MatchLevel.COLOUR_SHAPE_MATCH, MatchLevel.COLOUR_MATCH]
    basis: str


class MentionResolution(Contract):
    mention: Mention
    status: Literal["CANDIDATES", "UNRESOLVED", "CONTEXT_REVIEW"]
    candidates: list[Candidate]
    limitations: list[str]
    clarification: str
    needs_review: Literal[True] = True


class ResolutionResult(Contract):
    patient_id: int = Field(gt=0)
    as_of: date
    event_id: str
    consultation_id: str
    segment_id: str
    revision: int
    sequence: int
    status: Literal["ANALYZED", "PROVISIONAL"]
    resolutions: list[MentionResolution]
    limitations: list[str]
    persisted: Literal[False] = False

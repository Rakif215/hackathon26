from typing import Literal, Protocol

from pydantic import Field, StrictInt

from hackathon26.evidence_check.models import EvidenceResult
from hackathon26.listener.models import Contract


class ModelReply(Contract):
    text: str
    stop_reason: str
    guardrail_assessed: bool
    model_id: str


class EvidenceModel(Protocol):
    def generate(self, packet: str) -> ModelReply: ...


class Selection(Contract):
    rule_id: int = Field(strict=True)
    section_id: int = Field(strict=True)
    quote: str = Field(max_length=4000)
    lab_ids: list[StrictInt] = Field(max_length=512)


class ModelSelection(Contract):
    items: list[Selection] = Field(min_length=1, max_length=64)


class Summary(Contract):
    rule_id: int
    section_id: int
    quote: str
    lab_ids: list[int]
    text: Literal["Potential interaction for clinician review."] = "Potential interaction for clinician review."
    needs_review: Literal[True] = True


class SynthesisResult(Contract):
    status: Literal["GENERATED", "NOT_REQUESTED", "BLOCKED", "UNAVAILABLE", "INVALID_OUTPUT"]
    guardrail_status: Literal["ASSESSED", "INTERVENED", "UNCONFIRMED", "NOT_CONFIGURED", "NOT_REQUESTED"]
    summaries: list[Summary]
    evidence: EvidenceResult
    message: str
    model_id: str | None = None
    persisted: Literal[False] = False

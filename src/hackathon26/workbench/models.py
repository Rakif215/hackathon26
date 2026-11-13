from typing import Literal, Self

from pydantic import Field, StrictBool, model_validator

from hackathon26.evidence_check.models import EvidenceResult
from hackathon26.listener.models import Contract
from hackathon26.replay.models import ReplaySnapshot
from hackathon26.resolution.models import RecordedMedication, ResolutionResult
from hackathon26.synthesis.models import SynthesisResult


class WorkbenchRequest(Contract):
    expected_sequence: int = Field(strict=True, ge=0, le=999999)
    candidate_drug_id: int | None = Field(default=None, strict=True, gt=0, le=9_999_999_999)
    include_synthesis: StrictBool = False

    @model_validator(mode="after")
    def explicit_candidate_for_synthesis(self) -> Self:
        if self.include_synthesis and self.candidate_drug_id is None:
            raise ValueError("Synthesis requires an explicitly selected candidate drug")
        return self


class StageProblem(Contract):
    stage: Literal["resolution", "evidence", "synthesis"]
    code: str
    message: str
    retryable: bool


class WorkbenchResult(Contract):
    status: Literal["READY", "COMPLETE", "PARTIAL"]
    replay: ReplaySnapshot
    medications: list[RecordedMedication] | None = None
    resolution: ResolutionResult | None = None
    evidence: EvidenceResult | None = None
    synthesis: SynthesisResult | None = None
    problems: list[StageProblem]
    limitations: list[str]
    persisted: Literal[False] = False

from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from hackathon26.listener.models import Contract


class EvidenceRequest(Contract):
    as_of: date
    candidate_drug_id: int | None = Field(default=None, strict=True, gt=0)
    candidate_class_name: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def one_candidate(self) -> Self:
        if (self.candidate_drug_id is None) == (self.candidate_class_name is None):
            raise ValueError("Supply exactly one candidate drug ID or class name")
        if self.candidate_class_name is not None and not self.candidate_class_name.strip():
            raise ValueError("Candidate class must not be blank")
        return self


class EvidenceRow(Contract):
    rule_id: int
    rule_name: str
    analyte: str
    direction: Literal["LOW", "HIGH"]
    supplying_medications: str | None
    section_id: int | None
    section_type: str | None
    label_set_id: str | None
    label_effective_at: date | None
    source_url: str | None
    content_sha256: str | None
    section_text: str | None
    evidence_quote: str | None
    lab_id: int | None
    value_num: Decimal | None
    unit: str | None
    ref_low: Decimal | None
    ref_high: Decimal | None
    measured_at: date | None


class LabObservation(Contract):
    lab_id: int
    value: Decimal
    unit: str | None
    measured_at: date
    outside_reference_range: bool


class EvidenceFinding(Contract):
    rule_id: int
    rule_name: str
    analyte: str
    direction: Literal["LOW", "HIGH"]
    supplying_medications: str | None
    section_id: int
    section_type: str
    label_set_id: str
    label_effective_at: date | None
    source_url: str
    content_sha256: str
    evidence_quote: str
    labs: list[LabObservation]
    limitations: list[str]
    needs_review: Literal[True] = True


class EvidenceResult(Contract):
    patient_id: int
    request: EvidenceRequest
    status: Literal["EVIDENCE_FOUND", "EVIDENCE_UNVERIFIED", "NO_DOCUMENTED_INTERACTION_FOUND"]
    message: str
    findings: list[EvidenceFinding]
    failures: list[str]
    limitations: list[str]
    persisted: Literal[False] = False

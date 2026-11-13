"""Direct-invocation synthesis job; cloud deployment/queue integration is separate."""

from typing import Any

from pydantic import Field

from hackathon26.evidence_check.models import EvidenceRequest
from hackathon26.evidence_check.repository import EvidenceRepository
from hackathon26.evidence_check.verify import verify_rows
from hackathon26.listener.models import Contract

from .gateway import BedrockModel
from .service import summarize


class SynthesisJob(Contract):
    patient_id: int = Field(strict=True, gt=0)
    request: EvidenceRequest


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    job = SynthesisJob.model_validate(event)
    rows = EvidenceRepository().fetch(job.patient_id, job.request)
    evidence = verify_rows(job.patient_id, job.request, rows)
    return summarize(evidence, BedrockModel()).model_dump(mode="json")

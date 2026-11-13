"""Local API entry point for the listener foundation."""

from typing import Annotated

from fastapi import FastAPI, HTTPException, Path

from hackathon26.listener.detect import detect_mentions
from hackathon26.listener.models import ListenerResult, TranscriptSegment
from hackathon26.resolution.models import ResolutionResult, ResolveRequest
from hackathon26.resolution.repository import (
    ExasolMedicationRepository, MedicationRepository, MedicationStoreUnavailable, UnknownPatient,
)
from hackathon26.resolution.resolve import resolve_segment
from hackathon26.evidence_check.models import EvidenceRequest, EvidenceResult
from hackathon26.evidence_check.repository import EvidenceRepository, EvidenceSource, EvidenceStoreUnavailable, UnknownCandidate
from hackathon26.evidence_check.verify import verify_rows
from hackathon26.reviews.models import ReviewRequest, ReviewResult
from hackathon26.reviews.repository import ReviewRepository, ReviewStore, ReviewConflict, ReviewStoreUnavailable, UnknownFinding
from hackathon26.synthesis.gateway import BedrockModel
from hackathon26.synthesis.models import EvidenceModel, SynthesisResult
from hackathon26.synthesis.service import summarize
from hackathon26.replay.http import ReplayStore, build_router
from hackathon26.replay.repository import ReplayRepository
from hackathon26.workbench.http import build_workbench_router
from hackathon26.workbench.service import Workbench


def create_app(medication_repository: MedicationRepository | None = None,
               evidence_repository: EvidenceSource | None = None,
               review_store: ReviewStore | None = None,
               synthesis_model: EvidenceModel | None = None,
               replay_store: ReplayStore | None = None) -> FastAPI:
    app = FastAPI(title="MedGuard listener", version="0.1.0")
    repository = medication_repository if medication_repository is not None else ExasolMedicationRepository()
    evidence_source = evidence_repository if evidence_repository is not None else EvidenceRepository()
    reviews = review_store if review_store is not None else ReviewRepository()
    model = synthesis_model if synthesis_model is not None else BedrockModel()
    replays = replay_store if replay_store is not None else ReplayRepository()
    app.include_router(build_router(replays))
    app.include_router(build_workbench_router(Workbench(replays, repository, evidence_source, model)))

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive", "mode": "stateless-listener"}

    @app.post("/api/v1/listener/analyze", response_model=ListenerResult)
    def analyze(segment: TranscriptSegment) -> ListenerResult:
        return detect_mentions(segment)

    @app.post("/api/v1/patients/{patient_id}/listener/resolve", response_model=ResolutionResult)
    def resolve(patient_id: Annotated[int, Path(gt=0)], request: ResolveRequest) -> ResolutionResult:
        try:
            medicines = repository.current_medications(patient_id, request.as_of)
        except UnknownPatient:
            raise HTTPException(status_code=404, detail="Synthetic patient not found") from None
        except MedicationStoreUnavailable:
            raise HTTPException(status_code=503, detail="Medication data unavailable or incompatible") from None
        return resolve_segment(patient_id, request, medicines)

    @app.post("/api/v1/patients/{patient_id}/evidence/check", response_model=EvidenceResult)
    def check_evidence(patient_id: Annotated[int, Path(gt=0)], request: EvidenceRequest) -> EvidenceResult:
        try:
            rows = evidence_source.fetch(patient_id, request)
        except UnknownPatient:
            raise HTTPException(status_code=404, detail="Synthetic patient not found") from None
        except UnknownCandidate:
            raise HTTPException(status_code=422, detail="Unknown candidate: no recorded class mapping") from None
        except EvidenceStoreUnavailable:
            raise HTTPException(status_code=503, detail="Evidence storage unavailable or incompatible") from None
        return verify_rows(patient_id, request, rows)

    @app.post("/api/v1/patients/{patient_id}/evidence/summarize", response_model=SynthesisResult)
    def summarize_evidence(patient_id: Annotated[int, Path(gt=0)], request: EvidenceRequest) -> SynthesisResult:
        evidence = check_evidence(patient_id, request)
        return summarize(evidence, model)

    @app.post("/api/v1/consultations/{consultation_id}/findings/{finding_id}/reviews", response_model=ReviewResult)
    def review_finding(consultation_id: Annotated[int, Path(gt=0, le=9_999_999_999)],
                       finding_id: Annotated[int, Path(gt=0, le=9_999_999_999)],
                       command: ReviewRequest) -> ReviewResult:
        try:
            return reviews.save(consultation_id, finding_id, command)
        except UnknownFinding:
            raise HTTPException(status_code=404, detail="Finding not found in this synthetic consultation") from None
        except ReviewConflict:
            raise HTTPException(status_code=409, detail="Request key conflicts or finding already reviewed") from None
        except ReviewStoreUnavailable:
            raise HTTPException(status_code=503, detail="Review persistence unavailable; retry with the same request key") from None

    return app

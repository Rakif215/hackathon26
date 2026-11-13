from fastapi.testclient import TestClient

from hackathon26.api import create_app
from hackathon26.evidence_check.repository import EvidenceStoreUnavailable


class Source:
    def fetch(self, patient_id, request):
        if patient_id==503: raise EvidenceStoreUnavailable("private details")
        return []


class NeverCallModel:
    def generate(self, packet): raise AssertionError("No evidence must not call the model")


def test_summarize_fetches_server_evidence_and_bypasses_model_on_no_hit():
    with TestClient(create_app(evidence_repository=Source(),synthesis_model=NeverCallModel())) as client:
        response=client.post("/api/v1/patients/1/evidence/summarize",json={"as_of":"2026-11-13","candidate_drug_id":4})
    assert response.status_code==200
    assert response.json()["status"]=="NOT_REQUESTED"
    assert response.json()["evidence"]["status"]=="NO_DOCUMENTED_INTERACTION_FOUND"


def test_caller_cannot_submit_fake_verified_evidence():
    with TestClient(create_app(evidence_repository=Source(),synthesis_model=NeverCallModel())) as client:
        response=client.post("/api/v1/patients/1/evidence/summarize",json={"as_of":"2026-11-13","candidate_drug_id":4,"findings":[{"invented":"evidence"}]})
    assert response.status_code==422


def test_evidence_outage_is_not_synthesized_or_reported_as_no_hit():
    with TestClient(create_app(evidence_repository=Source(),synthesis_model=NeverCallModel())) as client:
        response=client.post("/api/v1/patients/503/evidence/summarize",json={"as_of":"2026-11-13","candidate_drug_id":4})
    assert response.status_code==503
    assert "private" not in response.text

from fastapi.testclient import TestClient

from hackathon26.api import create_app
from hackathon26.evidence_check.repository import EvidenceStoreUnavailable, UnknownCandidate
from hackathon26.resolution.repository import UnknownPatient


class Repository:
    def fetch(self, patient_id, request):
        if patient_id == 404: raise UnknownPatient()
        if patient_id == 503: raise EvidenceStoreUnavailable("private")
        if request.candidate_drug_id == 999: raise UnknownCandidate()
        return []


def test_evidence_endpoint_no_hit_is_explicit_and_not_saved():
    with TestClient(create_app(evidence_repository=Repository())) as client:
        response = client.post("/api/v1/patients/1/evidence/check", json={"as_of":"2026-11-13", "candidate_drug_id":4})
    assert response.status_code == 200
    assert response.json()["status"] == "NO_DOCUMENTED_INTERACTION_FOUND"
    assert response.json()["persisted"] is False


def test_evidence_endpoint_failure_states_are_distinct():
    with TestClient(create_app(evidence_repository=Repository())) as client:
        for patient, candidate, expected in [(404,4,404), (503,4,503), (1,999,422)]:
            response = client.post(f"/api/v1/patients/{patient}/evidence/check", json={"as_of":"2026-11-13", "candidate_drug_id":candidate})
            assert response.status_code == expected
            assert "private" not in response.text


def test_ambiguous_candidate_request_is_rejected():
    with TestClient(create_app(evidence_repository=Repository())) as client:
        response = client.post("/api/v1/patients/1/evidence/check", json={"as_of":"2026-11-13"})
    assert response.status_code == 422

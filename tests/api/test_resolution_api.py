from fastapi.testclient import TestClient

from hackathon26.api import create_app
from hackathon26.resolution.models import RecordedMedication
from hackathon26.resolution.repository import MedicationStoreUnavailable, UnknownPatient


class SyntheticRepository:
    def current_medications(self, patient_id, as_of):
        if patient_id == 404:
            raise UnknownPatient()
        if patient_id == 503:
            raise MedicationStoreUnavailable("private connection details")
        return [RecordedMedication(patient_med_id=11, drug_id=1, generic_name="Ramipril",
                                   strength="5 mg", color="white", shape="round",
                                   appearance_strength="5 mg", appearance_source="synthetic fixture")]


def payload(**updates):
    return {"as_of": "2026-11-13", "segment": {
        "schema_version": "1", "event_id": "e", "consultation_id": "c", "segment_id": "s",
        "revision": 1, "sequence": 1, "speaker": "PATIENT", "text": "I take the white one.",
        "is_final": True, "source": "script", "occurred_at": "2026-11-13T10:00:00Z",
    } | updates}


def test_resolution_api_uses_patient_list_without_confirming_or_saving():
    with TestClient(create_app(medication_repository=SyntheticRepository())) as client:
        response = client.post("/api/v1/patients/1/listener/resolve", json=payload())
    assert response.status_code == 200
    data = response.json()
    assert data["resolutions"][0]["candidates"][0]["match_level"] == "COLOUR_MATCH"
    assert data["resolutions"][0]["needs_review"] is True
    assert data["persisted"] is False


def test_missing_patient_and_database_failure_are_distinct():
    with TestClient(create_app(medication_repository=SyntheticRepository())) as client:
        assert client.post("/api/v1/patients/404/listener/resolve", json=payload()).status_code == 404
        response = client.post("/api/v1/patients/503/listener/resolve", json=payload())
    assert response.status_code == 503
    assert "private" not in response.text


def test_invalid_patient_date_and_partial_input():
    with TestClient(create_app(medication_repository=SyntheticRepository())) as client:
        assert client.post("/api/v1/patients/0/listener/resolve", json=payload()).status_code == 422
        assert client.post("/api/v1/patients/1/listener/resolve", json={"segment": payload()["segment"]}).status_code == 422
        response = client.post("/api/v1/patients/1/listener/resolve", json=payload(is_final=False))
    assert response.status_code == 200
    assert response.json()["status"] == "PROVISIONAL"
    assert response.json()["resolutions"] == []

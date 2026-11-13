from fastapi.testclient import TestClient

from hackathon26.api import create_app
from hackathon26.replay.models import ReplaySnapshot
from hackathon26.replay.repository import ReplayConflict, ReplayStoreUnavailable, UnknownReplay


class Store:
    def get(self,consultation_id,replay_id):
        if consultation_id==404: raise UnknownReplay()
        if consultation_id==503: raise ReplayStoreUnavailable("private details")
        return ReplaySnapshot(consultation_id=consultation_id,patient_id=1,replay_id=replay_id,
            created_at="2026-11-13T09:00:00Z",sequence=0,total_utterances=2,status="READY",
            utterances=[],last_segment=None,last_analysis=None,limitations=["Synthetic development"])
    def start(self,consultation_id,command): return self.get(consultation_id,123)
    def advance(self,consultation_id,replay_id,command): raise ReplayConflict()


def test_start_and_restore_routes_return_persisted_progress():
    with TestClient(create_app(replay_store=Store())) as client:
        response=client.post("/api/v1/consultations/1/replays",json={"idempotency_key":"start-key-001"})
        assert response.status_code==200
        data=response.json()
        assert data["progress_persisted"] is True and data["sequence"]==0
        assert client.get("/api/v1/consultations/1/replays/123").json()==data


def test_replay_not_found_conflict_and_storage_failure():
    with TestClient(create_app(replay_store=Store())) as client:
        assert client.get("/api/v1/consultations/404/replays/123").status_code==404
        response=client.get("/api/v1/consultations/503/replays/123")
        assert response.status_code==503 and "private" not in response.text
        assert client.post("/api/v1/consultations/1/replays/123/advance",json={"idempotency_key":"next-key-001","expected_sequence":0}).status_code==409


def test_invalid_cursor_and_ids_are_rejected():
    with TestClient(create_app(replay_store=Store())) as client:
        assert client.post("/api/v1/consultations/1/replays/123/advance",json={"idempotency_key":"next-key-001","expected_sequence":-1}).status_code==422
        assert client.get("/api/v1/consultations/0/replays/123").status_code==422

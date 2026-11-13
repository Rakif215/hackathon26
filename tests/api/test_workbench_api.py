from fastapi.testclient import TestClient

from hackathon26.api import create_app
from hackathon26.replay.models import ReplaySnapshot
from hackathon26.replay.repository import ReplayStoreUnavailable, UnknownReplay


class Replays:
    def get(self,consultation_id,replay_id):
        if consultation_id==404: raise UnknownReplay()
        if consultation_id==503: raise ReplayStoreUnavailable("private details")
        return ReplaySnapshot(consultation_id=consultation_id,patient_id=1,replay_id=replay_id,
            created_at="2026-11-13T09:00:00Z",sequence=0,total_utterances=3,status="READY",
            utterances=[],last_segment=None,last_analysis=None,limitations=["Synthetic test"])


def test_ready_workbench_does_not_call_live_dependencies():
    with TestClient(create_app(replay_store=Replays())) as client:
        response=client.post("/api/v1/consultations/7/replays/123/workbench",json={"expected_sequence":0})
    assert response.status_code==200
    assert response.json()["status"]=="READY"
    assert response.json()["evidence"] is None


def test_stale_cursor_and_wrong_replay_keep_error_semantics():
    with TestClient(create_app(replay_store=Replays())) as client:
        assert client.post("/api/v1/consultations/7/replays/123/workbench",json={"expected_sequence":1}).status_code==409
        assert client.post("/api/v1/consultations/404/replays/123/workbench",json={"expected_sequence":0}).status_code==404
        response=client.post("/api/v1/consultations/503/replays/123/workbench",json={"expected_sequence":0})
        assert response.status_code==503 and "private" not in response.text


def test_caller_cannot_override_server_patient_or_submit_raw_transcript():
    with TestClient(create_app(replay_store=Replays())) as client:
        response=client.post("/api/v1/consultations/7/replays/123/workbench",json={"expected_sequence":0,"patient_id":2,"text":"invented"})
    assert response.status_code==422

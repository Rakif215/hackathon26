from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from hackathon26.api import create_app
from hackathon26.listener.lambda_handler import handler


def payload(**updates):
    return {"schema_version": "1", "event_id": "evt-1", "consultation_id": "demo-1",
            "segment_id": "seg-1", "revision": 1, "sequence": 1, "speaker": "PATIENT",
            "text": "I take something for my knee.", "is_final": True,
            "source": "script", "occurred_at": "2026-11-13T10:00:00Z"} | updates


def test_http_and_direct_lambda_return_identical_analysis():
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/listener/analyze", json=payload())
    assert response.status_code == 200
    result = response.json()
    assert result == handler(payload(), None)
    assert result["mentions"][0]["kind"] == "INDICATION"
    assert result["persisted"] is False
    assert result["limitations"]


def test_invalid_http_input_is_rejected():
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/listener/analyze", json=payload(sequence=-1))
    assert response.status_code == 422


def test_partial_http_input_is_provisional():
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/listener/analyze", json=payload(is_final=False))
    assert response.status_code == 200
    assert response.json()["status"] == "PROVISIONAL"
    assert response.json()["mentions"] == []


def test_health_does_not_claim_dependencies_are_ready():
    with TestClient(create_app()) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive", "mode": "stateless-listener"}


def test_invalid_direct_lambda_input_fails_invocation():
    with pytest.raises(ValidationError):
        handler(payload(source="microphone"), None)

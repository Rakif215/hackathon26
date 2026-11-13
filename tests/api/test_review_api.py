from datetime import datetime, timezone

from fastapi.testclient import TestClient

from hackathon26.api import create_app
from hackathon26.reviews.models import ReviewResult
from hackathon26.reviews.repository import ReviewConflict, ReviewStoreUnavailable, UnknownFinding


class Store:
    def save(self, consultation_id, finding_id, command):
        if finding_id == 404: raise UnknownFinding()
        if finding_id == 409: raise ReviewConflict()
        if finding_id == 503: raise ReviewStoreUnavailable("private details")
        return ReviewResult(review_id=finding_id, consultation_id=consultation_id,
                            finding_id=finding_id, reviewer=command.reviewer,
                            decision=command.decision, note=command.note,
                            decided_at=datetime(2026, 11, 13, tzinfo=timezone.utc))


def payload(**updates):
    return {"idempotency_key":"review-key-001", "reviewer":"Dr. Demo",
            "decision":"ACCEPTED", "note":"Evidence reviewed"} | updates


def test_explicit_review_is_saved_and_returned():
    with TestClient(create_app(review_store=Store())) as client:
        response = client.post("/api/v1/consultations/1/findings/9/reviews", json=payload())
    assert response.status_code == 200
    assert response.json()["persisted"] is True
    assert response.json()["finding_id"] == 9


def test_review_failure_states_do_not_claim_saved():
    with TestClient(create_app(review_store=Store())) as client:
        for code in (404,409,503):
            response = client.post(f"/api/v1/consultations/1/findings/{code}/reviews", json=payload())
            assert response.status_code == code
            assert "private" not in response.text
            assert "persisted" not in response.json()


def test_override_without_reason_and_invalid_ids_are_rejected():
    with TestClient(create_app(review_store=Store())) as client:
        assert client.post("/api/v1/consultations/1/findings/9/reviews", json=payload(decision="OVERRIDDEN",note=" ")).status_code == 422
        assert client.post("/api/v1/consultations/0/findings/9/reviews", json=payload()).status_code == 422

import pytest
from pydantic import ValidationError

from hackathon26.synthesis import lambda_handler


class Source:
    def fetch(self, patient_id, request):
        assert patient_id==1
        assert request.candidate_drug_id==4
        return []


def test_lambda_fetches_evidence_instead_of_accepting_a_verified_packet(monkeypatch):
    monkeypatch.setattr(lambda_handler,"EvidenceRepository",Source)
    result=lambda_handler.handler({"patient_id":1,"request":{"as_of":"2026-11-13","candidate_drug_id":4}},None)
    assert result["status"]=="NOT_REQUESTED"
    assert result["persisted"] is False


def test_lambda_rejects_arbitrary_evidence_payload():
    with pytest.raises(ValidationError): lambda_handler.handler({"patient_id":1,"evidence":{"status":"EVIDENCE_FOUND"}},None)

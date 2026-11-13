import json
from datetime import date

import pytest

from hackathon26.evidence_check.models import EvidenceFinding, EvidenceRequest, EvidenceResult, LabObservation
from hackathon26.synthesis.models import ModelReply
from hackathon26.synthesis.service import summarize


def evidence(status="EVIDENCE_FOUND"):
    return EvidenceResult(patient_id=1, request=EvidenceRequest(as_of=date(2026,11,13),candidate_drug_id=4),
        status=status, message="Test only", failures=[], limitations=["Actual exposure unverified"], findings=[
            EvidenceFinding(rule_id=1,rule_name="synthetic interaction rule",analyte="EGFR",direction="LOW",
                supplying_medications="ramipril, furosemide",section_id=10,section_type="drug_interactions",
                label_set_id="synthetic-label",label_effective_at=None,source_url="https://example.com/synthetic",
                content_sha256="a"*64,evidence_quote="Synthetic example evidence.",labs=[],limitations=["No recent labs"])
        ] if status=="EVIDENCE_FOUND" else [])


def output(**updates):
    return json.dumps({"items":[{"rule_id":1,"section_id":10,"quote":"Synthetic example evidence.","lab_ids":[]} | updates]})


class Model:
    def __init__(self, reply=None, error=None):
        self.reply=reply or ModelReply(text=output(),stop_reason="end_turn",guardrail_assessed=True,model_id="test-model")
        self.error=error
        self.calls=0
    def generate(self, packet):
        self.calls+=1
        if self.error: raise self.error
        return self.reply


def test_exact_verified_selection_is_rendered_with_evidence_and_limitations():
    result=summarize(evidence(),Model())
    assert result.status=="GENERATED"
    assert result.guardrail_status=="ASSESSED"
    assert result.summaries[0].quote=="Synthetic example evidence."
    assert result.summaries[0].text=="Potential interaction for clinician review."
    assert result.evidence.findings[0].limitations==["No recent labs"]
    assert result.persisted is False


@pytest.mark.parametrize("text",[output(rule_id=999),output(section_id=999),output(quote="invented"),
    output(lab_ids=[999]),'{"items":[]}', '{"items":[{},{}]}', 'not json',
    output(summary="Stop the medicine")])
def test_unsupported_or_incomplete_output_is_rejected(text):
    result=summarize(evidence(),Model(ModelReply(text=text,stop_reason="end_turn",guardrail_assessed=True,model_id="test")))
    assert result.status=="INVALID_OUTPUT"
    assert result.summaries==[]
    assert result.evidence.findings


@pytest.mark.parametrize("status",["NO_DOCUMENTED_INTERACTION_FOUND","EVIDENCE_UNVERIFIED"])
def test_unverified_or_no_hit_evidence_never_calls_model(status):
    model=Model()
    assert summarize(evidence(status),model).status=="NOT_REQUESTED"
    assert model.calls==0


def test_blocked_output_is_not_published():
    result=summarize(evidence(),Model(ModelReply(text=output(),stop_reason="guardrail_intervened",guardrail_assessed=True,model_id="test")))
    assert result.status=="BLOCKED"
    assert result.guardrail_status=="INTERVENED"
    assert result.summaries==[]


def test_guardrail_assessment_required_before_publication():
    result=summarize(evidence(),Model(ModelReply(text=output(),stop_reason="end_turn",guardrail_assessed=False,model_id="test")))
    assert result.status=="INVALID_OUTPUT"
    assert result.guardrail_status=="UNCONFIRMED"


def test_transport_failure_keeps_evidence_and_exposes_no_error_details():
    result=summarize(evidence(),Model(error=OSError("private service detail")))
    assert result.status=="UNAVAILABLE"
    assert result.evidence.findings
    assert "private" not in result.model_dump_json()


@pytest.mark.parametrize("lab_id",[True,"1",1.0])
def test_lab_references_require_exact_integer_types(lab_id):
    packet=evidence()
    finding=packet.findings[0].model_copy(update={"labs":[LabObservation(lab_id=1,value="48",unit="unit",measured_at=date(2026,11,1),outside_reference_range=False)]})
    packet=packet.model_copy(update={"findings":[finding]})
    model=Model(ModelReply(text=output(lab_ids=[lab_id]),stop_reason="end_turn",guardrail_assessed=True,model_id="test"))
    assert summarize(packet,model).status=="INVALID_OUTPUT"

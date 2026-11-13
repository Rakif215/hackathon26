from datetime import date
from hashlib import sha256

import pytest
from pydantic import ValidationError

from hackathon26.evidence_check.models import EvidenceRow
from hackathon26.listener.models import TranscriptSegment
from hackathon26.replay.models import ReplaySnapshot, ScriptUtterance
from hackathon26.resolution.models import RecordedMedication
from hackathon26.resolution.repository import MedicationStoreUnavailable
from hackathon26.synthesis.models import ModelReply
from hackathon26.workbench.models import WorkbenchRequest
from hackathon26.workbench.service import Workbench, WorkbenchConflict


class Replays:
    def __init__(self,sequence=1,changes=False): self.sequence=sequence; self.changes=changes; self.calls=0
    def get(self,consultation_id,replay_id):
        self.calls+=1
        sequence=self.sequence+(1 if self.changes and self.calls>1 else 0)
        segment=TranscriptSegment(schema_version="1",event_id="e1",consultation_id="7",segment_id="11",
            revision=1,sequence=sequence,speaker="PATIENT",text="I take something for my knee.",is_final=True,
            source="script",occurred_at="2026-11-13T09:00:00Z") if sequence else None
        return ReplaySnapshot(consultation_id=7,patient_id=1,replay_id=123,created_at="2026-11-13T08:00:00Z",
            sequence=sequence,total_utterances=3,status="PLAYING" if sequence else "READY",
            utterances=[ScriptUtterance(utterance_id=11,sequence=sequence,speaker="PATIENT",text=segment.text,offset_ms=0)] if segment else [],
            last_segment=segment,last_analysis=None,limitations=["Synthetic test"])


class Medicines:
    def __init__(self,error=False): self.calls=[]; self.error=error
    def current_medications(self,patient_id,as_of):
        self.calls.append((patient_id,as_of))
        if self.error: raise MedicationStoreUnavailable()
        return [RecordedMedication(patient_med_id=1,drug_id=1,generic_name="ramipril",strength="5 mg")]


class Evidence:
    def __init__(self,with_match=False): self.calls=[]; self.with_match=with_match
    def fetch(self,patient_id,request):
        self.calls.append((patient_id,request))
        if not self.with_match: return []
        return [EvidenceRow(rule_id=1,rule_name="Synthetic rule",analyte="EGFR",direction="LOW",
            supplying_medications="ramipril",section_id=10,section_type="drug_interactions",
            label_set_id="synthetic",label_effective_at=None,source_url="https://example.com/synthetic",
            content_sha256=sha256(b"Synthetic evidence.").hexdigest(),section_text="Synthetic evidence.",
            evidence_quote="Synthetic evidence.",lab_id=None,value_num=None,unit=None,ref_low=None,ref_high=None,measured_at=None)]


class Model:
    def __init__(self): self.calls=0
    def generate(self,packet):
        self.calls+=1
        return ModelReply(text='{"items":[{"rule_id":1,"section_id":10,"quote":"Synthetic evidence.","lab_ids":[]}]}',
            stop_reason="end_turn",guardrail_assessed=True,model_id="test-model")


def setup(replays=None,medicines=None,evidence=None):
    replays=replays or Replays(); medicines=medicines or Medicines(); evidence=evidence or Evidence(); model=Model()
    return Workbench(replays,medicines,evidence,model),medicines,evidence,model


def test_unidentified_mention_does_not_trigger_evidence_or_model():
    service,medicines,evidence,model=setup()
    result=service.run(7,123,WorkbenchRequest(expected_sequence=1))
    assert result.status=="COMPLETE"
    assert result.resolution.resolutions[0].status=="UNRESOLVED"
    assert medicines.calls==[(1,date(2026,11,13))]
    assert result.medications[0].generic_name=="ramipril"
    assert evidence.calls==[] and model.calls==0
    assert result.evidence is None and result.persisted is False


def test_explicit_candidate_is_bound_to_replay_patient_and_date():
    service,_,evidence,model=setup()
    result=service.run(7,123,WorkbenchRequest(expected_sequence=1,candidate_drug_id=4))
    assert evidence.calls[0][0]==1
    assert evidence.calls[0][1].candidate_drug_id==4
    assert evidence.calls[0][1].as_of==date(2026,11,13)
    assert result.evidence.status=="NO_DOCUMENTED_INTERACTION_FOUND"
    assert model.calls==0


def test_guarded_synthesis_requires_explicit_opt_in_and_verified_evidence():
    service,_,_,model=setup(evidence=Evidence(with_match=True))
    result=service.run(7,123,WorkbenchRequest(expected_sequence=1,candidate_drug_id=4,include_synthesis=True))
    assert result.synthesis.status=="GENERATED"
    assert model.calls==1


def test_resolution_outage_returns_partial_not_empty_success():
    service,_,evidence,model=setup(medicines=Medicines(error=True))
    result=service.run(7,123,WorkbenchRequest(expected_sequence=1))
    assert result.status=="PARTIAL" and result.resolution is None
    assert result.problems[0].stage=="resolution"
    assert result.problems[0].retryable is True
    assert evidence.calls==[] and model.calls==0


def test_ready_replay_does_not_touch_downstream_dependencies():
    service,medicines,evidence,model=setup(replays=Replays(sequence=0))
    assert service.run(7,123,WorkbenchRequest(expected_sequence=0)).status=="READY"
    assert medicines.calls==evidence.calls==[] and model.calls==0


@pytest.mark.parametrize("replays,expected",[(Replays(sequence=2),1),(Replays(changes=True),1)])
def test_stale_and_concurrently_advanced_replays_do_not_publish_mixed_state(replays,expected):
    service,_,_,_=setup(replays=replays)
    with pytest.raises(WorkbenchConflict): service.run(7,123,WorkbenchRequest(expected_sequence=expected))


def test_client_cannot_supply_patient_transcript_or_a_fake_evidence_packet():
    with pytest.raises(ValidationError): WorkbenchRequest(expected_sequence=1,patient_id=2)
    with pytest.raises(ValidationError): WorkbenchRequest(expected_sequence=1,include_synthesis=True)


def test_future_label_is_withheld_before_model_use():
    class FutureEvidence(Evidence):
        def fetch(self,patient_id,request):
            return [row.model_copy(update={"label_effective_at":date(2027,1,1)}) for row in super().fetch(patient_id,request)]
    service,_,_,model=setup(evidence=FutureEvidence(with_match=True))
    result=service.run(7,123,WorkbenchRequest(expected_sequence=1,candidate_drug_id=4,include_synthesis=True))
    assert result.status=="PARTIAL"
    assert result.evidence.status=="EVIDENCE_UNVERIFIED"
    assert model.calls==0


def test_malformed_provider_response_preserves_usable_stages(monkeypatch):
    from hackathon26 import bedrock
    from hackathon26.synthesis.gateway import BedrockModel
    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID","test-guardrail")
    monkeypatch.setenv("BEDROCK_GUARDRAIL_VERSION","1")
    monkeypatch.setattr(bedrock,"guarded_converse",lambda *args,**kwargs:{"stopReason":None})
    service=Workbench(Replays(),Medicines(),Evidence(with_match=True),BedrockModel())
    result=service.run(7,123,WorkbenchRequest(expected_sequence=1,candidate_drug_id=4,include_synthesis=True))
    assert result.status=="PARTIAL"
    assert result.resolution is not None and result.evidence.status=="EVIDENCE_FOUND"
    assert result.synthesis.status=="INVALID_OUTPUT"

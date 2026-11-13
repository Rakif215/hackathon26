"""Bind analysis to server-owned replay state, without triggering clinical actions."""

from hackathon26.evidence_check.models import EvidenceRequest
from hackathon26.evidence_check.repository import EvidenceSource, EvidenceStoreUnavailable
from hackathon26.evidence_check.verify import verify_rows
from hackathon26.replay.http import ReplayStore
from hackathon26.replay.models import ReplaySnapshot
from hackathon26.resolution.models import ResolveRequest
from hackathon26.resolution.repository import MedicationRepository, MedicationStoreUnavailable, UnknownPatient
from hackathon26.resolution.resolve import resolve_segment
from hackathon26.synthesis.models import EvidenceModel
from hackathon26.synthesis.service import summarize

from .models import StageProblem, WorkbenchRequest, WorkbenchResult


class WorkbenchConflict(Exception):
    """Replay state changed or does not match the requested turn."""


def _check_replay(snapshot: ReplaySnapshot, consultation_id: int, replay_id: int, expected: int) -> None:
    if (snapshot.consultation_id != consultation_id or snapshot.replay_id != replay_id or snapshot.sequence != expected):
        raise WorkbenchConflict("Replay identity or sequence changed")
    segment = snapshot.last_segment
    if segment is not None and (segment.consultation_id != str(consultation_id) or segment.sequence != expected):
        raise WorkbenchConflict("Replay transcript binding changed")
    if (expected == 0) != (segment is None):
        raise WorkbenchConflict("Replay cursor and transcript disagree")


class Workbench:
    def __init__(self, replays: ReplayStore, medicines: MedicationRepository,
                 evidence: EvidenceSource, model: EvidenceModel):
        self._replays, self._medicines, self._evidence, self._model = replays, medicines, evidence, model

    def run(self, consultation_id: int, replay_id: int, command: WorkbenchRequest) -> WorkbenchResult:
        snapshot = self._replays.get(consultation_id, replay_id)
        _check_replay(snapshot, consultation_id, replay_id, command.expected_sequence)
        limitations = [
            "Only explicitly requested stages are checked; COMPLETE does not establish medication compatibility or actual exposure.",
            "Workbench results are not persisted findings, candidate confirmations, clinician decisions or medication changes.",
            "Model calls occur only on explicit synthesis requests; repeating those requests may call the model again.",
            "Downstream data are read separately; this is not an atomic snapshot of all patient records.",
        ]
        if snapshot.last_segment is None:
            if command.candidate_drug_id is not None:
                raise WorkbenchConflict("Advance the replay before a turn-bound candidate check")
            return WorkbenchResult(status="READY", replay=snapshot, problems=[], limitations=limitations)
        segment = snapshot.last_segment
        as_of = segment.occurred_at.date()
        problems = []
        resolution = evidence = synthesis = medications = None
        try:
            medications = self._medicines.current_medications(snapshot.patient_id, as_of)
            resolution = resolve_segment(snapshot.patient_id, ResolveRequest(segment=segment, as_of=as_of), medications)
        except MedicationStoreUnavailable:
            problems.append(StageProblem(stage="resolution", code="DEPENDENCY_UNAVAILABLE", retryable=True,
                                         message="Patient medication data unavailable; no resolution result established."))
        except UnknownPatient:
            raise WorkbenchConflict("Replay patient association is no longer available") from None
        if command.candidate_drug_id is not None:
            request = EvidenceRequest(as_of=as_of, candidate_drug_id=command.candidate_drug_id)
            try:
                rows = self._evidence.fetch(snapshot.patient_id, request)
                evidence = verify_rows(snapshot.patient_id, request, rows)
                if evidence.status == "EVIDENCE_UNVERIFIED":
                    problems.append(StageProblem(stage="evidence", code="EVIDENCE_UNVERIFIED", retryable=False,
                                                 message="Source checks failed; findings were withheld."))
            except EvidenceStoreUnavailable:
                problems.append(StageProblem(stage="evidence", code="DEPENDENCY_UNAVAILABLE", retryable=True,
                                             message="Evidence data unavailable; no interaction result established."))
            except UnknownPatient:
                raise WorkbenchConflict("Replay patient association is no longer available") from None
            if command.include_synthesis and evidence is not None:
                synthesis = summarize(evidence, self._model)
                if synthesis.status in {"UNAVAILABLE", "INVALID_OUTPUT", "BLOCKED"}:
                    problems.append(StageProblem(stage="synthesis", code=synthesis.status,
                                                 message=synthesis.message,
                                                 retryable=synthesis.status == "UNAVAILABLE" and synthesis.guardrail_status != "NOT_CONFIGURED"))
        current = self._replays.get(consultation_id, replay_id)
        _check_replay(current, consultation_id, replay_id, command.expected_sequence)
        if current.patient_id != snapshot.patient_id or current.last_segment != snapshot.last_segment:
            raise WorkbenchConflict("Replay context changed during analysis")
        return WorkbenchResult(status="PARTIAL" if problems else "COMPLETE", replay=snapshot,
                               medications=medications,
                               resolution=resolution, evidence=evidence, synthesis=synthesis,
                               problems=problems, limitations=limitations)

from datetime import date

import pytest

from hackathon26.evidence_check.models import EvidenceRequest
from hackathon26.evidence_check.repository import EvidenceRepository, EvidenceStoreUnavailable, UnknownCandidate
from hackathon26.resolution.repository import UnknownPatient


class Rows:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows


class Connection:
    def __init__(self, patient=True, candidate=True):
        self.patient, self.candidate, self.calls = patient, candidate, []
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params):
        self.calls.append((sql, params))
        if "IS_SYNTHETIC" in sql: return Rows([(1,)] if self.patient else [])
        if not sql.lstrip().startswith("WITH"): return Rows([("NSAID",)] if self.candidate else [])
        return Rows([])


def request():
    return EvidenceRequest(as_of=date(2026, 11, 13), candidate_drug_id=4)


def test_valid_candidate_no_hit_and_bound_parameters():
    conn = Connection()
    assert EvidenceRepository(lambda: conn).fetch(1, request()) == []
    assert conn.calls[-1][1] == {"patient_id": 1, "as_of": "2026-11-13", "candidate_drug_id": 4, "candidate_class_name": None}


def test_unknown_candidate_does_not_run_join_or_return_no_hit():
    conn = Connection(candidate=False)
    with pytest.raises(UnknownCandidate): EvidenceRepository(lambda: conn).fetch(1, request())
    assert len(conn.calls) == 2


def test_unknown_patient_does_not_run_join():
    conn = Connection(patient=False)
    with pytest.raises(UnknownPatient): EvidenceRepository(lambda: conn).fetch(1, request())
    assert len(conn.calls) == 1


def test_database_error_is_not_an_empty_success():
    def unavailable(): raise OSError("private details")
    with pytest.raises(EvidenceStoreUnavailable) as error:
        EvidenceRepository(unavailable).fetch(1, request())
    assert "private" not in str(error.value)

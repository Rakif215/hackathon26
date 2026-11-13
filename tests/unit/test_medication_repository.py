from datetime import date

import pytest

from hackathon26.resolution.repository import ExasolMedicationRepository, MedicationStoreUnavailable, UnknownPatient


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, patient=True):
        self.patient = patient
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if "IS_SYNTHETIC" in sql:
            return Rows([(1,)] if self.patient else [])
        return Rows([(11, 1, "Ramipril", "5 mg", "white", "round", "DEMO", "5 mg", "Demo A", "synthetic")])


def test_repository_uses_bound_patient_date_and_preserves_sources():
    conn = Connection()
    records = ExasolMedicationRepository(lambda: conn).current_medications(1, date(2026, 11, 13))
    assert records[0].appearance_source == "synthetic"
    assert records[0].patient_med_id == 11
    assert conn.calls[0][1] == {"patient_id": 1}
    sql, params = conn.calls[1]
    assert params == {"patient_id": 1, "as_of": "2026-11-13"}
    assert "STARTED_ON" in sql and "STOPPED_ON" in sql


def test_unknown_or_non_synthetic_patient_is_not_an_empty_success():
    with pytest.raises(UnknownPatient):
        ExasolMedicationRepository(lambda: Connection(False)).current_medications(9, date(2026, 11, 13))


def test_connection_error_is_distinct_from_no_medications():
    def unavailable():
        raise OSError("sensitive connection details")
    with pytest.raises(MedicationStoreUnavailable) as error:
        ExasolMedicationRepository(unavailable).current_medications(1, date(2026, 11, 13))
    assert "sensitive" not in str(error.value)


def test_orphaned_active_medication_is_not_hidden_by_inner_join():
    conn = Connection()
    ExasolMedicationRepository(lambda: conn).current_medications(1, date(2026, 11, 13))
    assert "LEFT JOIN MEDGUARD.DRUG d" in conn.calls[1][0]

"""Opt-in, read-only Exasol SQL checks using inline synthetic CTEs, not stored patient data."""

from hashlib import sha256
import os

import pytest

from hackathon26.db import connect
from hackathon26.evidence_check.repository import EVIDENCE_JOIN_QUERY

pytestmark = pytest.mark.skipif(os.getenv("MEDGUARD_INTEGRATION") != "1", reason="Opt-in Exasol connection")

_FIXTURES = """
WITH DRUG_CLASS AS (
 SELECT 1 DRUG_ID, 'ACE inhibitor' CLASS_NAME UNION ALL
 SELECT 2, 'beta blocker' UNION ALL SELECT 3, 'loop diuretic' UNION ALL SELECT 4, 'NSAID'
), DRUG AS (
 SELECT 1 DRUG_ID, 'ramipril' GENERIC_NAME UNION ALL
 SELECT 2, 'metoprolol' UNION ALL SELECT 3, 'furosemide'
), PATIENT_MEDICATION AS (
 SELECT 1 PATIENT_ID, 1 DRUG_ID, DATE '2026-01-01' STARTED_ON, CAST(NULL AS DATE) STOPPED_ON UNION ALL
 SELECT 1, 2, DATE '2026-01-01', CAST(NULL AS DATE) UNION ALL
 SELECT 1, 3, DATE '2026-01-01', CAST(NULL AS DATE)
), RISK_LAB_RULE AS (
 SELECT 1 RULE_ID, 'synthetic renal rule' RULE_NAME, 'EGFR' ANALYTE, 'LOW' DIRECTION,
        10 EVIDENCE_SECTION_ID, 'synthetic evidence' EVIDENCE_QUOTE UNION ALL
 SELECT 2, 'synthetic renal rule', 'CREATININE', 'HIGH', 10, 'synthetic evidence' UNION ALL
 SELECT 3, 'synthetic potassium rule', 'POTASSIUM', 'HIGH', 10, 'synthetic evidence'
), RISK_RULE_CLASS AS (
 SELECT 1 RULE_ID, 'NSAID' CLASS_NAME UNION ALL SELECT 1, 'ACE inhibitor' UNION ALL
 SELECT 1, 'loop diuretic' UNION ALL SELECT 2, 'NSAID' UNION ALL SELECT 2, 'ACE inhibitor' UNION ALL
 SELECT 2, 'loop diuretic' UNION ALL SELECT 3, 'ACE inhibitor'
), DRUG_LABEL_SECTION AS (
 SELECT 10 SECTION_ID, 'drug_interactions' SECTION_TYPE, 'synthetic-label' LABEL_SET_ID,
        DATE '2022-07-01' LABEL_EFFECTIVE_AT, 'https://example.com/synthetic' SOURCE_URL,
        {fixture_hash} CONTENT_SHA256, 'synthetic evidence' SECTION_TEXT
), LAB_RESULT AS (
 SELECT 1 LAB_ID, 1 PATIENT_ID, 'EGFR' ANALYTE, 62 VALUE_NUM, 'unit' UNIT,
        60 REF_LOW, CAST(NULL AS DECIMAL(10,3)) REF_HIGH, DATE '2026-05-14' MEASURED_AT UNION ALL
 SELECT 2, 1, 'EGFR', 55, 'unit', 60, NULL, DATE '2026-08-14' UNION ALL
 SELECT 3, 1, 'EGFR', 48, 'unit', 60, NULL, DATE '2026-11-01' UNION ALL
 SELECT 4, 1, 'CREATININE', 0.97, 'unit', NULL, 1.1, DATE '2026-05-14' UNION ALL
 SELECT 5, 1, 'CREATININE', 1.07, 'unit', NULL, 1.1, DATE '2026-08-14' UNION ALL
 SELECT 6, 1, 'CREATININE', 1.20, 'unit', NULL, 1.1, DATE '2026-11-01' UNION ALL
 SELECT 7, 1, 'POTASSIUM', 4.6, 'unit', NULL, 5.0, DATE '2026-05-14' UNION ALL
 SELECT 8, 1, 'POTASSIUM', 4.9, 'unit', NULL, 5.0, DATE '2026-08-14' UNION ALL
 SELECT 9, 1, 'POTASSIUM', 5.1, 'unit', NULL, 5.0, DATE '2026-11-01'
),
"""


def test_actual_exasol_join_with_inline_synthetic_data():
    # Only identifiers are replaced to shadow canonical tables with read-only fixtures.
    sql = _FIXTURES + EVIDENCE_JOIN_QUERY.strip().removeprefix("WITH ").replace("MEDGUARD.", "")
    params = {"patient_id": 1, "as_of": "2026-11-13", "candidate_drug_id": 4,
              "candidate_class_name": None, "fixture_hash": sha256(b"synthetic evidence").hexdigest()}
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        assert len(rows) == 6
        assert [float(row[14]) for row in rows] == [62, 55, 48, 0.97, 1.07, 1.2]
        assert {row[4] for row in rows} == {"furosemide, ramipril"}
        assert conn.execute(sql, params | {"candidate_drug_id": None, "candidate_class_name": "NSAID"}).fetchall() == rows
        assert conn.execute(sql, params | {"candidate_drug_id": 2}).fetchall() == []
        potassium = conn.execute(sql, params | {"candidate_drug_id": 1}).fetchall()
        assert len(potassium) == 3
        assert all(row[4] is None for row in potassium)
        assert conn.execute(sql, params | {"patient_id": 999}).fetchall() == []
        missing_labs = conn.execute(sql, params | {"as_of": "2028-01-01"}).fetchall()
        assert len(missing_labs) == 2
        assert all(row[13] is None for row in missing_labs)

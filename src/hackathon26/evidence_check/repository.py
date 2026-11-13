"""Read-only canonical Exasol evidence join; all values use bound parameters."""

from collections.abc import Callable
from typing import Protocol

from pyexasol import ExaConnection, ExaError

from hackathon26.db import connect
from hackathon26.resolution.repository import UnknownPatient

from .models import EvidenceRequest, EvidenceRow


class UnknownCandidate(Exception):
    """No known class mapping for the supplied candidate."""


class EvidenceStoreUnavailable(Exception):
    """Evidence data cannot be read or decoded."""


class EvidenceSource(Protocol):
    def fetch(self, patient_id: int, request: EvidenceRequest) -> list[EvidenceRow]: ...


EVIDENCE_JOIN_QUERY = """
WITH candidate_classes AS (
    SELECT DISTINCT CLASS_NAME FROM MEDGUARD.DRUG_CLASS
    WHERE ({candidate_drug_id!d} IS NOT NULL AND DRUG_ID = {candidate_drug_id!d})
       OR ({candidate_class_name} IS NOT NULL AND CLASS_NAME = {candidate_class_name})
), current_meds AS (
    SELECT DISTINCT pm.DRUG_ID, d.GENERIC_NAME, dc.CLASS_NAME
    FROM MEDGUARD.PATIENT_MEDICATION pm
    JOIN MEDGUARD.DRUG d ON d.DRUG_ID = pm.DRUG_ID
    JOIN MEDGUARD.DRUG_CLASS dc ON dc.DRUG_ID = pm.DRUG_ID
    WHERE pm.PATIENT_ID = {patient_id!d}
      AND pm.STARTED_ON IS NOT NULL
      AND pm.STARTED_ON <= TO_DATE({as_of}, 'YYYY-MM-DD')
      AND (pm.STOPPED_ON IS NULL OR pm.STOPPED_ON > TO_DATE({as_of}, 'YYYY-MM-DD'))
), available_classes AS (
    SELECT CLASS_NAME FROM candidate_classes
    UNION SELECT CLASS_NAME FROM current_meds
), matching_rules AS (
    SELECT r.* FROM MEDGUARD.RISK_LAB_RULE r
    WHERE EXISTS (
        SELECT 1 FROM MEDGUARD.RISK_RULE_CLASS rc
        JOIN candidate_classes cc ON cc.CLASS_NAME = rc.CLASS_NAME
        WHERE rc.RULE_ID = r.RULE_ID
    ) AND NOT EXISTS (
        SELECT 1 FROM MEDGUARD.RISK_RULE_CLASS rc
        WHERE rc.RULE_ID = r.RULE_ID AND NOT EXISTS (
            SELECT 1 FROM available_classes ac WHERE ac.CLASS_NAME = rc.CLASS_NAME
        )
    )
), supplier_names AS (
    SELECT DISTINCT r.RULE_ID, cm.GENERIC_NAME
    FROM matching_rules r
    JOIN MEDGUARD.RISK_RULE_CLASS rc ON rc.RULE_ID = r.RULE_ID
    JOIN current_meds cm ON cm.CLASS_NAME = rc.CLASS_NAME
    WHERE NOT EXISTS (SELECT 1 FROM candidate_classes cc WHERE cc.CLASS_NAME = rc.CLASS_NAME)
), suppliers AS (
    SELECT RULE_ID, LISTAGG(GENERIC_NAME, ', ') WITHIN GROUP (ORDER BY GENERIC_NAME) AS SUPPLYING_DRUG_NAMES
    FROM supplier_names GROUP BY RULE_ID
)
SELECT r.RULE_ID, r.RULE_NAME, r.ANALYTE, r.DIRECTION, sp.SUPPLYING_DRUG_NAMES,
       s.SECTION_ID, s.SECTION_TYPE, s.LABEL_SET_ID, s.LABEL_EFFECTIVE_AT,
       s.SOURCE_URL, s.CONTENT_SHA256, s.SECTION_TEXT, r.EVIDENCE_QUOTE,
       l.LAB_ID, l.VALUE_NUM, l.UNIT, l.REF_LOW, l.REF_HIGH, l.MEASURED_AT
FROM matching_rules r
LEFT JOIN suppliers sp ON sp.RULE_ID = r.RULE_ID
LEFT JOIN MEDGUARD.DRUG_LABEL_SECTION s ON s.SECTION_ID = r.EVIDENCE_SECTION_ID
LEFT JOIN MEDGUARD.LAB_RESULT l ON l.PATIENT_ID = {patient_id!d} AND l.ANALYTE = r.ANALYTE
    AND l.MEASURED_AT BETWEEN ADD_DAYS(TO_DATE({as_of}, 'YYYY-MM-DD'), -365)
                        AND TO_DATE({as_of}, 'YYYY-MM-DD')
ORDER BY r.RULE_ID, l.MEASURED_AT, l.LAB_ID
"""


class EvidenceRepository:
    def __init__(self, connection_factory: Callable[[], ExaConnection] = connect):
        self._connect = connection_factory

    def fetch(self, patient_id: int, request: EvidenceRequest) -> list[EvidenceRow]:
        params = {"patient_id": patient_id, "as_of": request.as_of.isoformat(),
                  "candidate_drug_id": request.candidate_drug_id,
                  "candidate_class_name": request.candidate_class_name}
        try:
            with self._connect() as conn:
                patients = conn.execute(
                    "SELECT PATIENT_ID FROM MEDGUARD.PATIENT WHERE PATIENT_ID = {patient_id!d} AND IS_SYNTHETIC = TRUE",
                    {"patient_id": patient_id},
                ).fetchall()
                if not patients:
                    raise UnknownPatient()
                classes = conn.execute(
                    "SELECT CLASS_NAME FROM MEDGUARD.DRUG_CLASS WHERE "
                    "({candidate_drug_id!d} IS NOT NULL AND DRUG_ID = {candidate_drug_id!d}) OR "
                    "({candidate_class_name} IS NOT NULL AND CLASS_NAME = {candidate_class_name})",
                    {"candidate_drug_id": request.candidate_drug_id, "candidate_class_name": request.candidate_class_name},
                ).fetchall()
                if not classes:
                    raise UnknownCandidate()
                rows = conn.execute(EVIDENCE_JOIN_QUERY, params).fetchall()
            return [EvidenceRow(**dict(zip(EvidenceRow.model_fields, row, strict=True))) for row in rows]
        except (ExaError, OSError, RuntimeError, ValueError) as error:
            raise EvidenceStoreUnavailable("Evidence storage unavailable or incompatible") from error
